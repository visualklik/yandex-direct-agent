import io, re, pandas as pd

def load_direct(path, sheet=0):
    """Читает выгрузку Мастера отчётов (csv/tsv/xlsx). Возвращает (df, meta)."""
    if path.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
        hdr = next(i for i, row in raw.iterrows()
                   if row.astype(str).str.contains(r"Показ|Клик", case=False, na=False).any())
        meta = [" ".join(raw.iloc[i].dropna().astype(str)) for i in range(hdr)]
        df = raw.iloc[hdr + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    else:
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = open(path, encoding=enc).read(); break
            except UnicodeDecodeError:
                continue
        lines = text.splitlines()
        hdr = next(i for i, l in enumerate(lines) if re.search(r"Показ|Клик", l, re.I))
        meta, head = lines[:hdr], lines[hdr]
        sep = max((";", "\t", ","), key=head.count)
        df = pd.read_csv(io.StringIO("\n".join(lines[hdr:])), sep=sep, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and c.lower() not in ("nan", "none")]]
    first = df.iloc[:, 0].astype(str).str.strip().str.lower()
    df = df[~first.isin(["итого", "total", "nan", ""])]
    return df.reset_index(drop=True), meta

def num(s):
    s = str(s).replace("\xa0", "").replace(" ", "").replace("%", "").replace(",", ".")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else 0.0

def to_num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(num)
    return df
