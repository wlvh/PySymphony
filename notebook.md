# ============================================================
# Leakage-safe baseline for bound prediction
# Revised after audit
#
# Assumes existing DataFrames:
#   ans, csad, smad
# ============================================================

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

# Conservative baseline:
# premium_band may be generated after quote / underwriting decision,
# so exclude it unless business confirms it is available pre-bound.
DROP_PREMIUM_BAND = True

MAX_CAT_CARDINALITY = 60
NUMERIC_PARSE_THRESHOLD = 0.85

VALID_FRACTION = 0.25

STRICT_ASOF_HIDDEN_PREDICTION = True
MIN_TRAIN_FOR_HIDDEN_MODEL = 80


# ----------------------------
# 1. Small utilities
# ----------------------------

def display_or_print(df, n=None):
    out = df if n is None else df.head(n)
    try:
        display(out)
    except Exception:
        print(out.to_string(index=False))


def clean_key(s):
    """
    Normalize DUNS-like keys.
    Keeps digits only.
    """
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


def to_binary_label(s):
    """
    Robust conversion for bound.
    """
    num = pd.to_numeric(s, errors="coerce")

    txt = s.astype("string").str.strip().str.upper()
    mapped = txt.map({
        "TRUE": 1,
        "T": 1,
        "YES": 1,
        "Y": 1,
        "1": 1,
        "BOUND": 1,

        "FALSE": 0,
        "F": 0,
        "NO": 0,
        "N": 0,
        "0": 0,
        "NOT BOUND": 0,
        "UNBOUND": 0,
    })

    out = num.where(num.notna(), mapped)
    out = pd.to_numeric(out, errors="coerce")
    out = out.where(out.isin([0, 1]))

    return out.astype(float)


def parse_csad_datepll(s):
    """
    Parse csad DATEPLL.

    Expected examples:
        MAR23
        APR23
        2023-03-01

    Avoids relying on system locale for %b.
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")

    raw = s.astype("string").str.strip().str.upper()

    month_map = {
        "JAN": "01",
        "FEB": "02",
        "MAR": "03",
        "APR": "04",
        "MAY": "05",
        "JUN": "06",
        "JUL": "07",
        "AUG": "08",
        "SEP": "09",
        "OCT": "10",
        "NOV": "11",
        "DEC": "12",
    }

    mon = raw.str.extract(r"^([A-Z]{3})", expand=False).map(month_map)
    yr = raw.str.extract(r"(\d{2,4})$", expand=False)

    yr4 = yr.copy()
    yr4 = yr4.where(yr4.str.len().eq(4), "20" + yr4)

    manual = pd.to_datetime(yr4 + "-" + mon + "-01", errors="coerce")

    # Fallback for ISO-like strings, e.g. 2023-03-01.
    iso_like = raw.str.contains(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", na=False)
    fallback = pd.to_datetime(raw.where(iso_like), errors="coerce")

    return manual.combine_first(fallback)


def parse_smad_arch_dte(s):
    """
    Parse smad ARCH_DTE.

    Supports:
        datetime64
        08202023 / 8202023    -> MMDDYYYY
        20230820              -> YYYYMMDD
        2023-08-20            -> ISO-like
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")

    raw = s.astype("string").str.strip()

    iso_like = raw.str.contains(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", na=False)
    direct = pd.to_datetime(raw.where(iso_like), errors="coerce")

    digits = (
        raw
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D+", "", regex=True)
        .replace({"": pd.NA})
    )

    digits_z = digits.copy()
    short = digits_z.notna() & digits_z.str.len().lt(8)
    digits_z.loc[short] = digits_z.loc[short].str.zfill(8)

    digits8 = digits_z.where(digits_z.str.len().eq(8))

    dt_mdy = pd.to_datetime(digits8, format="%m%d%Y", errors="coerce")
    dt_ymd = pd.to_datetime(digits8, format="%Y%m%d", errors="coerce")

    # Choose the dominant format, but allow fallback row-wise.
    if dt_ymd.notna().sum() > dt_mdy.notna().sum():
        parsed = dt_ymd.combine_first(dt_mdy)
    else:
        parsed = dt_mdy.combine_first(dt_ymd)

    return direct.combine_first(parsed)


def choose_best_key_col(df, ref_key, preferred=None, label="table"):
    """
    Pick the DUNS-like column with the largest overlap with answer keys.
    This avoids hardcoding weird names like DUNS@.
    """
    preferred = preferred or []

    preferred_existing = [c for c in preferred if c in df.columns]
    duns_like = [
        c for c in df.columns
        if "DUNS" in c.upper() and c not in preferred_existing
    ]

    candidates = preferred_existing + duns_like

    if not candidates:
        raise KeyError(
            f"No DUNS-like columns found in {label}. "
            f"Columns are: {list(df.columns)[:50]}..."
        )

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


def prefix_except(df, prefix, except_cols):
    except_cols = set(except_cols)
    return df.rename(columns={
        c: f"{prefix}{c}"
        for c in df.columns
        if c not in except_cols
    })


def make_ohe():
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def choose_schema(df, candidate_cols, train_index):
    """
    Decide numeric vs categorical using training rows only.

    This version avoids pandas PerformanceWarning:
    instead of inserting columns into X_all one by one,
    it collects Series in a dict and builds the DataFrame once.
    """
    col_data = {}

    numeric_cols = []
    categorical_cols = []
    dropped_reason = {}

    train_index = pd.Index(train_index)

    for c in candidate_cols:
        s = df[c]

        # 1. Drop raw datetime columns.
        # We already use derived date features like renew_year / renew_month.
        if pd.api.types.is_datetime64_any_dtype(s):
            dropped_reason[c] = "raw_datetime"
            continue

        # 2. Native numeric / bool columns.
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            x = pd.to_numeric(s, errors="coerce").astype(float)

            if x.loc[train_index].nunique(dropna=True) <= 1:
                dropped_reason[c] = "constant_numeric"
                continue

            col_data[c] = x
            numeric_cols.append(c)
            continue

        # 3. Object / string columns.
        # First clean obvious missing tokens.
        txt = s.astype("string").str.strip()
        txt = txt.replace({
            "": pd.NA,
            "NAN": pd.NA,
            "nan": pd.NA,
            "NONE": pd.NA,
            "None": pd.NA,
            "NULL": pd.NA,
            "<NA>": pd.NA,
        })

        # Try to parse as numeric.
        # This handles object columns that are actually numbers stored as strings.
        num_txt = (
            txt
            .str.replace(",", "", regex=False)
            .str.replace("$", "", regex=False)
            .str.replace("%", "", regex=False)
        )

        num = pd.to_numeric(num_txt, errors="coerce")

        train_txt = txt.loc[train_index]
        train_num = num.loc[train_index]
        nonnull_train = train_txt.notna()

        if nonnull_train.any():
            parse_rate = train_num[nonnull_train].notna().mean()
        else:
            parse_rate = 0.0

        # 4. If most non-null training values parse as numbers,
        # treat the column as numeric.
        if parse_rate >= NUMERIC_PARSE_THRESHOLD:
            x = num.astype(float)

            if x.loc[train_index].nunique(dropna=True) <= 1:
                dropped_reason[c] = "constant_after_numeric_parse"
                continue

            col_data[c] = x
            numeric_cols.append(c)
            continue

        # 5. Otherwise treat as categorical, but only if not too high-cardinality.
        card = train_txt.nunique(dropna=True)

        if card <= 1:
            dropped_reason[c] = "constant_categorical"
            continue

        if card > MAX_CAT_CARDINALITY:
            dropped_reason[c] = f"high_cardinality_{card}"
            continue

        # Store categorical as object with np.nan for missing values,
        # so SimpleImputer can handle it cleanly later.
        col_data[c] = txt.astype(object).where(txt.notna(), np.nan)
        categorical_cols.append(c)

    # Build the DataFrame once. This avoids DataFrame fragmentation.
    if col_data:
        X_all = pd.DataFrame(col_data, index=df.index).copy()
    else:
        X_all = pd.DataFrame(index=df.index)

    return X_all, numeric_cols, categorical_cols, dropped_reason


def make_logistic_model(numeric_cols, categorical_cols):
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

    pre = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
    )

    clf = LogisticRegression(
        max_iter=5000,
        solver="liblinear",
        C=0.5,
        class_weight=None,
    )

    return Pipeline(steps=[
        ("preprocess", pre),
        ("model", clf),
    ])


def temporal_purged_split(known_df, val_fraction=0.25):
    """
    Validation = later renew_date.
    Training = earlier renew_date.
    Purge all DUNS keys appearing in validation from training.
    """
    known_df = known_df[known_df["renew_dt"].notna()].copy()

    if len(known_df) == 0:
        raise ValueError("No known rows with valid renew_dt.")

    dates = known_df["renew_dt"].sort_values()

    # Try several cutoffs in case the first one creates tiny / one-class validation.
    cut_fracs = [
        1 - val_fraction,
        0.70,
        0.65,
        0.60,
        0.55,
        0.50,
    ]

    best = None

    for frac in cut_fracs:
        pos = int(np.floor(len(dates) * frac))
        pos = max(0, min(pos, len(dates) - 1))

        cutoff = dates.iloc[pos]

        val_mask = known_df["renew_dt"] >= cutoff
        val_keys = set(known_df.loc[val_mask, "_k"].dropna())

        train_mask = (
            (known_df["renew_dt"] < cutoff)
            & (~known_df["_k"].isin(val_keys))
        )

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

        if (
            candidate["train_n"] >= 100
            and candidate["val_n"] >= 50
            and candidate["train_classes"] == 2
            and candidate["val_classes"] == 2
        ):
            return train_idx, val_idx, cutoff

    print("WARNING: Could not find an ideal temporal split. Using best available split.")
    return best["train_idx"], best["val_idx"], best["cutoff"]


def print_validation_metrics(y_true, pred, label="model"):
    print(f"\nValidation metrics: {label}")

    if pd.Series(y_true).nunique() == 2:
        print(f"ROC AUC:           {roc_auc_score(y_true, pred):.4f}")
        print(f"Average Precision: {average_precision_score(y_true, pred):.4f}")
    else:
        print("ROC AUC:           NA, validation has only one class")
        print("Average Precision: NA, validation has only one class")

    print(f"LogLoss:           {log_loss(y_true, pred, labels=[0, 1]):.4f}")
    print(f"Brier:             {brier_score_loss(y_true, pred):.4f}")
    print(f"Accuracy@0.5:      {accuracy_score(y_true, (pred >= 0.5).astype(int)):.4f}")


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

# Normalize known answer-side features.
for c in ["broker", "subline", "insured_country", "region", "industry_group"]:
    if c in ans0.columns:
        ans0[f"{c}_norm"] = (
            ans0[c]
            .astype("string")
            .str.strip()
            .str.lower()
        )

if "premium_band" in ans0.columns:
    ans0["premium_band_norm"] = (
        ans0["premium_band"]
        .astype("string")
        .str.strip()
    )

if "in_appetite" in ans0.columns:
    ans0["in_appetite_norm"] = (
        ans0["in_appetite"]
        .astype("string")
        .str.strip()
        .str.upper()
        .map({
            "TRUE": "1",
            "T": "1",
            "YES": "1",
            "Y": "1",
            "1": "1",

            "FALSE": "0",
            "F": "0",
            "NO": "0",
            "N": "0",
            "0": "0",
        })
    )

# Renewal timing is known at scoring time.
ans0["renew_year"] = ans0["renew_dt"].dt.year
ans0["renew_month"] = ans0["renew_dt"].dt.month
ans0["renew_quarter"] = ans0["renew_dt"].dt.quarter
ans0["renew_month_index"] = ans0["renew_dt"].dt.year * 12 + ans0["renew_dt"].dt.month

print("\nAnswer label distribution:")
print(ans0["y"].value_counts(dropna=False).to_string())
print(f"known labels: {ans0['y'].notna().sum()}")
print(f"hidden labels: {ans0['y'].isna().sum()}")


# ----------------------------
# 3. Auto-detect external keys
# ----------------------------

ref_key = ans0["_k"]

CSAD_K = choose_best_key_col(
    csad,
    ref_key=ref_key,
    preferred=["DUNS_NUMBER", "DUNS"],
    label="csad",
)

SMAD_K = choose_best_key_col(
    smad,
    ref_key=ref_key,
    preferred=["DUNS@", "DUNS_NUMBER", "DUNS"],
    label="smad",
)


# ----------------------------
# 4. Prepare csad / smad
# ----------------------------

csad0 = csad.copy()
csad0["_k"] = clean_key(csad0[CSAD_K])
csad0["dt"] = parse_csad_datepll(csad0["DATEPLL"]) if "DATEPLL" in csad0.columns else pd.NaT
csad0["has_row"] = 1

smad0 = smad.copy()
smad0["_k"] = clean_key(smad0[SMAD_K])
smad0["dt"] = parse_smad_arch_dte(smad0["ARCH_DTE"]) if "ARCH_DTE" in smad0.columns else pd.NaT
smad0["has_row"] = 1

# Empty keys should not participate in merge.
csad0 = csad0[csad0["_k"].notna()].copy()
smad0 = smad0[smad0["_k"].notna()].copy()

# If future data versions produce duplicate keys, keep latest available snapshot.
if csad0["_k"].duplicated().any():
    print("WARNING: csad has duplicate keys. Keeping latest dt per key.")
    csad0 = csad0.sort_values("dt").drop_duplicates("_k", keep="last")

if smad0["_k"].duplicated().any():
    print("WARNING: smad has duplicate keys. Keeping latest dt per key.")
    smad0 = smad0.sort_values("dt").drop_duplicates("_k", keep="last")

print("\nExternal date ranges:")
print(f"csad dt range: {csad0['dt'].min()} -- {csad0['dt'].max()} | parse_rate={csad0['dt'].notna().mean():.3f}")
print(f"smad dt range: {smad0['dt'].min()} -- {smad0['dt'].max()} | parse_rate={smad0['dt'].notna().mean():.3f}")

csad_r = prefix_except(csad0.drop(columns=[CSAD_K]), "csad_", except_cols=["_k"])
smad_r = prefix_except(smad0.drop(columns=[SMAD_K]), "smad_", except_cols=["_k"])


# ----------------------------
# 5. Merge
# ----------------------------

m = (
    ans0
    .merge(csad_r, on="_k", how="left", validate="m:1")
    .merge(smad_r, on="_k", how="left", validate="m:1")
)

print("\nMerge diagnostics:")
print(f"answer rows: {len(ans0)}")
print(f"merged rows: {len(m)}")

if len(m) != len(ans0):
    raise RuntimeError("Merge changed row count. This indicates a 1:n merge problem.")


# ----------------------------
# 6. As-of availability gate
# ----------------------------
# Critical leakage guard:
# External snapshot is usable only if snapshot date <= renewal date.

for src in ["csad", "smad"]:
    dt_col = f"{src}_dt"
    has_col = f"{src}_has_row"
    avail_col = f"{src}_available_at_renewal"

    if dt_col not in m.columns:
        m[dt_col] = pd.NaT

    m[avail_col] = (
        m[dt_col].notna()
        & m["renew_dt"].notna()
        & (m[dt_col] <= m["renew_dt"])
    ).astype("int8")
    # only use csad&smad features when their date <= renewal date

    protected = {dt_col, has_col, avail_col}

    source_payload_cols = [
        c for c in m.columns
        if c.startswith(f"{src}_") and c not in protected
    ]

    # If a source is not available at renewal time,
    # remove all of its payload features.
    m.loc[m[avail_col].eq(0), source_payload_cols] = np.nan

print("\nAvailability diagnostics:")
print(f"rows with no raw csad match: {m['csad_has_row'].isna().sum() if 'csad_has_row' in m.columns else 'NA'}")
print(f"rows with no raw smad match: {m['smad_has_row'].isna().sum() if 'smad_has_row' in m.columns else 'NA'}")
print(f"rows with csad available at renewal: {m['csad_available_at_renewal'].sum()}")
print(f"rows with smad available at renewal: {m['smad_available_at_renewal'].sum()}")
print(f"rows with neither available: {((m['csad_available_at_renewal'] == 0) & (m['smad_available_at_renewal'] == 0)).sum()}")

if "smad_has_row" in m.columns:
    blocked_smad = (
        m["smad_has_row"].notna()
        & (m["smad_available_at_renewal"] == 0)
    ).sum()
    print(f"rows where smad matched but was blocked as future info: {blocked_smad}")


# ----------------------------
# 7. Candidate features
# ----------------------------

drop_exact = {
    "_row_id",
    "y",
    "bound",
    ANS_K,
    "_k",
    "renew_date",
    "renew_dt",

    # Use normalized versions / derived versions instead.
    "broker",
    "subline",
    "insured_country",
    "region",
    "industry_group",
    "premium_band",
    "in_appetite",
    "quarter",
    "year",

    # Diagnostic match flags. Use availability flags instead.
    "csad_has_row",
    "smad_has_row",

    # Entity / name-like field from answer.
    "insured_name_scoring",
}

if DROP_PREMIUM_BAND:
    drop_exact.add("premium_band_norm")

# Conservative leak / ID / metadata pattern.
# Note: CONTROL is intentionally NOT dropped.
bad_feature_pattern = re.compile(
    r"(?:^|_)("
    r"duns|"
    r"filler|"
    r"telephone|phone|"
    r"business_name|"
    r"street_address|"
    r"postal_code|zip_code|"
    r"ingest|file_name|timestamp|"
    r"as_of_date|datepll|arch_dte"
    r")(?:_|$)",
    flags=re.IGNORECASE,
)

candidate_cols = []

for c in m.columns:
    if c in drop_exact:
        continue

    # Raw snapshot dates are not features.
    # Availability flags are features.
    if c.endswith("_dt"):
        continue

    if bad_feature_pattern.search(c):
        continue

    candidate_cols.append(c)

print(f"\nCandidate feature columns before schema selection: {len(candidate_cols)}")
print(f"DROP_PREMIUM_BAND = {DROP_PREMIUM_BAND}")


# ----------------------------
# 8. Train / validation split
# ----------------------------

known = m[m["y"].notna()].copy()
hidden = m[m["y"].isna()].copy()

train_idx, val_idx, cutoff = temporal_purged_split(
    known,
    val_fraction=VALID_FRACTION,
)

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
# 9. Schema selection and baseline model
# ----------------------------

X_all, numeric_cols, categorical_cols, dropped_reason = choose_schema(
    m,
    candidate_cols=candidate_cols,
    train_index=train_idx,
)

used_cols = numeric_cols + categorical_cols

print("\nSchema selected from training rows only:")
print(f"numeric cols: {len(numeric_cols)}")
print(f"categorical cols: {len(categorical_cols)}")
print(f"dropped cols: {len(dropped_reason)}")

print("\nFirst 30 used columns:")
print(used_cols[:30])

model = make_logistic_model(numeric_cols, categorical_cols)

model.fit(X_all.loc[train_idx, used_cols], train_y)

val_pred = model.predict_proba(X_all.loc[val_idx, used_cols])[:, 1]

print_validation_metrics(val_y, val_pred, label="leakage-safe logistic baseline")

base_rate = train_y.mean()
base_pred = np.repeat(base_rate, len(val_y))

print("\nBase-rate-only comparison:")
print(f"train base rate: {base_rate:.4f}")
print(f"base LogLoss:    {log_loss(val_y, base_pred, labels=[0, 1]):.4f}")
print(f"base Brier:      {brier_score_loss(val_y, base_pred):.4f}")


# ----------------------------
# 10. Segmented validation metrics
# ----------------------------

val_frame = m.loc[val_idx, [
    "renew_year",
    "csad_available_at_renewal",
    "smad_available_at_renewal",
]].copy()

val_frame["y"] = val_y.values
val_frame["pred"] = val_pred

print("\nSegmented validation AUC by external availability:")
for keys, g in val_frame.groupby(["csad_available_at_renewal", "smad_available_at_renewal"]):
    if len(g) < 10:
        continue

    if g["y"].nunique() < 2:
        print(f"csad={keys[0]} smad={keys[1]}: n={len(g)}, AUC=NA one-class")
        continue

    print(
        f"csad={keys[0]} smad={keys[1]}: "
        f"n={len(g)}, "
        f"actual_rate={g['y'].mean():.3f}, "
        f"pred_mean={g['pred'].mean():.3f}, "
        f"AUC={roc_auc_score(g['y'], g['pred']):.3f}"
    )

print("\nSegmented validation AUC by renew_year:")
for yr, g in val_frame.groupby("renew_year"):
    if pd.isna(yr) or len(g) < 10:
        continue

    if g["y"].nunique() < 2:
        print(f"year={int(yr)}: n={len(g)}, AUC=NA one-class")
        continue

    print(
        f"year={int(yr)}: "
        f"n={len(g)}, "
        f"actual_rate={g['y'].mean():.3f}, "
        f"pred_mean={g['pred'].mean():.3f}, "
        f"AUC={roc_auc_score(g['y'], g['pred']):.3f}"
    )


# ----------------------------
# 11. Calibration table
# ----------------------------

print("\nCalibration table, quantile bins:")
if val_y.nunique() == 2 and len(val_y) >= 20:
    n_bins = min(10, max(2, len(val_y) // 20))

    prob_true, prob_pred_bin = calibration_curve(
        val_y,
        val_pred,
        n_bins=n_bins,
        strategy="quantile",
    )

    calib = pd.DataFrame({
        "mean_predicted_probability": prob_pred_bin,
        "actual_bound_rate": prob_true,
    })

    print(calib.to_string(index=False))
else:
    print("Not enough validation data for calibration table.")


# ----------------------------
# 12. Hidden prediction
# ----------------------------
# Strict version:
# For each hidden renewal date, train only on known rows with renew_dt < hidden renew_dt.
# This avoids using future labels to predict past hidden records.

hidden_pred = pd.Series(index=hidden.index, dtype=float)
hidden_pred_source = pd.Series(index=hidden.index, dtype=object)

if len(hidden) == 0:
    print("\nNo hidden rows to predict.")
else:
    print("\nHidden rows:")
    print(f"hidden n: {len(hidden)}")
    print(f"hidden date range: {hidden['renew_dt'].min()} -- {hidden['renew_dt'].max()}")

    if STRICT_ASOF_HIDDEN_PREDICTION:
        print("\nUsing strict past-only walk-forward prediction for hidden rows.")

        hidden_with_date = hidden[hidden["renew_dt"].notna()].copy()
        hidden_no_date = hidden[hidden["renew_dt"].isna()].copy()

        for pred_dt, group in hidden_with_date.groupby("renew_dt", sort=True):
            pred_idx = group.index
            pred_keys = set(m.loc[pred_idx, "_k"].dropna())

            local_train_idx = known.index[
                (known["renew_dt"] < pred_dt)
                & (~known["_k"].isin(pred_keys))
            ]

            local_y = m.loc[local_train_idx, "y"].dropna().astype(int)

            if (
                len(local_train_idx) >= MIN_TRAIN_FOR_HIDDEN_MODEL
                and local_y.nunique() == 2
            ):
                X_local, num_local, cat_local, dropped_local = choose_schema(
                    m,
                    candidate_cols=candidate_cols,
                    train_index=local_train_idx,
                )

                used_local = num_local + cat_local

                local_model = make_logistic_model(num_local, cat_local)
                local_model.fit(
                    X_local.loc[local_train_idx, used_local],
                    local_y,
                )

                hidden_pred.loc[pred_idx] = local_model.predict_proba(
                    X_local.loc[pred_idx, used_local]
                )[:, 1]

                hidden_pred_source.loc[pred_idx] = f"model_past_only_n={len(local_train_idx)}"

            else:
                # Conservative fallback.
                # Uses only past labels; if none exist, use neutral 0.5.
                if len(local_y) > 0:
                    prior = local_y.mean()
                    source = f"past_prior_only_n={len(local_y)}"
                else:
                    prior = 0.5
                    source = "neutral_prior_no_past_labels"

                hidden_pred.loc[pred_idx] = prior
                hidden_pred_source.loc[pred_idx] = source

        if len(hidden_no_date) > 0:
            hidden_pred.loc[hidden_no_date.index] = 0.5
            hidden_pred_source.loc[hidden_no_date.index] = "neutral_prior_missing_renew_dt"

    else:
        print("\nUsing all known labels for hidden prediction.")
        print("This is less conservative if hidden rows include earlier renewal dates.")

        X_final, num_final, cat_final, dropped_final = choose_schema(
            m,
            candidate_cols=candidate_cols,
            train_index=known.index,
        )

        used_final = num_final + cat_final

        final_model = make_logistic_model(num_final, cat_final)
        final_model.fit(
            X_final.loc[known.index, used_final],
            known["y"].astype(int),
        )

        hidden_pred.loc[hidden.index] = final_model.predict_proba(
            X_final.loc[hidden.index, used_final]
        )[:, 1]

        hidden_pred_source.loc[hidden.index] = f"model_all_known_n={len(known)}"


    output_cols = [
        "_row_id",
        ANS_K,
        "renew_date",
        "broker",
        "subline",
        "insured_country",
        "region",
        "industry_group",
        "premium_band",
        "in_appetite",
        "csad_available_at_renewal",
        "smad_available_at_renewal",
    ]

    output_cols = [c for c in output_cols if c in m.columns]

    bound_baseline_predictions = m.loc[hidden.index, output_cols].copy()
    bound_baseline_predictions["pred_bound_proba"] = hidden_pred.loc[hidden.index].values
    bound_baseline_predictions["pred_bound_label_05"] = (
        bound_baseline_predictions["pred_bound_proba"] >= 0.5
    ).astype(int)
    bound_baseline_predictions["prediction_source"] = hidden_pred_source.loc[hidden.index].values

    bound_baseline_predictions = bound_baseline_predictions.sort_values(
        "pred_bound_proba",
        ascending=False,
    )

    print("\nHidden prediction probability summary:")
    print(bound_baseline_predictions["pred_bound_proba"].describe().to_string())

    print("\nPrediction source counts:")
    print(bound_baseline_predictions["prediction_source"].value_counts().to_string())

    print("\nTop hidden predictions:")
    display_or_print(bound_baseline_predictions.head(30))

    # Optional save path for Databricks:
    # bound_baseline_predictions.to_csv("/dbfs/FileStore/bound_baseline_predictions.csv", index=False)
