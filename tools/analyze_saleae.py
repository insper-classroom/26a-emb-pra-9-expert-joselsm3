#!/usr/bin/env python3
"""
Analisa CSV exportado do Saleae Logic 2 e calcula metricas RTOS por canal:
  - WCET        : maior largura de pulso HIGH (us)
  - Jitter      : max(periodo) - min(periodo) entre bordas de subida (us)
  - Periodo medio: media dos periodos entre subidas (ms)
  - Deadline Miss Rate: % de periodos > deadline esperado

Uso:
    python tools/analyze_saleae.py capture.csv
    python tools/analyze_saleae.py capture.csv --deadline 10,10,10,10
    python tools/analyze_saleae.py capture.csv --deadline 10,10,10,10 --min-pulses 100

Formato do CSV esperado (export "Digital Data" do Saleae Logic 2):
    Time [s],Channel 0,Channel 1,Channel 2,Channel 3
    0.000000000,0,0,0,0
    0.000001234,1,0,0,0
    ...

Mapeamento de canais:
    CH0 (Channel 0) -> mpu_task    deadline padrao: 10 ms
    CH1 (Channel 1) -> fusion_task deadline padrao: 10 ms
    CH2 (Channel 2) -> uart_task   deadline padrao: 10 ms
    CH3 (Channel 3) -> pwm_task    deadline padrao: 10 ms
"""

import sys
import csv
import argparse


TASK_NAMES = ["mpu_task", "fusion_task", "uart_task", "pwm_task"]


def parse_args():
    p = argparse.ArgumentParser(
        description="Calcula metricas RTOS a partir de CSV do Saleae Logic 2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("csv_file", help="Arquivo CSV exportado do Saleae Logic 2")
    p.add_argument(
        "--deadline",
        default="10,10,10,10",
        help="Deadlines em ms para CH0,CH1,CH2,CH3 (default: 10,10,10,10)",
    )
    p.add_argument(
        "--min-pulses",
        type=int,
        default=10,
        help="Numero minimo de pulsos para calcular metricas (default: 10)",
    )
    return p.parse_args()


def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw = f.read()

    # Remove linhas de metadados do Saleae que comecam com ";;"
    lines = [l for l in raw.splitlines() if not l.startswith(";;")]
    reader = csv.DictReader(lines)
    for row in reader:
        rows.append(row)
    return reader.fieldnames, rows


def find_column(fieldnames, candidates):
    """Retorna o primeiro nome de coluna que corresponde a algum candidato."""
    fl = [f.strip().lower() for f in fieldnames]
    for c in candidates:
        for i, f in enumerate(fl):
            if c.lower() in f:
                return fieldnames[i]
    return None


def build_edges(rows, time_col, val_col):
    """
    Retorna lista de (time_s, edge_type) para um canal.
    edge_type in ('rising', 'falling').
    Suporta tanto formato denso (todos os samples) quanto esparso (so transicoes).
    """
    edges = []
    prev_val = None
    for row in rows:
        try:
            t = float(row[time_col])
            v = int(float(row[val_col]))
        except (ValueError, KeyError):
            continue
        if prev_val is None:
            prev_val = v
            continue
        if v != prev_val:
            edges.append((t, "rising" if v == 1 else "falling"))
        prev_val = v
    return edges


def compute_metrics(edges, deadline_ms):
    """
    Retorna dict com:
      wcet_us, jitter_us, avg_period_ms, min_period_ms, max_period_ms,
      deadline_misses, miss_rate_pct, n_pulses, n_periods
    """
    rising  = [t for t, e in edges if e == "rising"]
    falling = [t for t, e in edges if e == "falling"]

    # Emparelha cada rising com o proximo falling
    pulse_widths_us = []
    fi = 0
    for rt in rising:
        while fi < len(falling) and falling[fi] <= rt:
            fi += 1
        if fi < len(falling):
            pulse_widths_us.append((falling[fi] - rt) * 1e6)
            fi += 1

    # Periodos entre bordas de subida consecutivas
    periods_ms = [(rising[i + 1] - rising[i]) * 1e3 for i in range(len(rising) - 1)]

    if not pulse_widths_us:
        return None

    misses = sum(1 for p in periods_ms if p > deadline_ms) if periods_ms else 0
    miss_rate = misses / len(periods_ms) * 100.0 if periods_ms else 0.0

    return {
        "wcet_us":       max(pulse_widths_us),
        "avg_wcet_us":   sum(pulse_widths_us) / len(pulse_widths_us),
        "jitter_us":     (max(periods_ms) - min(periods_ms)) * 1000.0 if len(periods_ms) >= 2 else 0.0,
        "avg_period_ms": sum(periods_ms) / len(periods_ms) if periods_ms else 0.0,
        "min_period_ms": min(periods_ms) if periods_ms else 0.0,
        "max_period_ms": max(periods_ms) if periods_ms else 0.0,
        "deadline_misses": misses,
        "miss_rate_pct": miss_rate,
        "n_pulses":      len(pulse_widths_us),
        "n_periods":     len(periods_ms),
    }


def fmt(val, unit="", decimals=1):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{unit}"


def print_table(all_metrics, deadlines_ms):
    col_w = 14
    label_w = 28
    sep = "-" * (label_w + col_w * 4)
    hdr = "=" * (label_w + col_w * 4)

    print()
    print(hdr)
    print("  METRICAS RTOS — Saleae Logic 2")
    print(hdr)
    header = f"{'Metrica':<{label_w}}" + "".join(f"{n:>{col_w}}" for n in TASK_NAMES)
    print(header)
    print(sep)

    def row(label, fn):
        vals = [fn(all_metrics[i]) if all_metrics[i] else "N/A" for i in range(4)]
        return f"{label:<{label_w}}" + "".join(f"{v:>{col_w}}" for v in vals)

    print(row("WCET (us)",            lambda m: fmt(m["wcet_us"])))
    print(row("WCET medio (us)",      lambda m: fmt(m["avg_wcet_us"])))
    print(row("Jitter (us)",          lambda m: fmt(m["jitter_us"])))
    print(row("Periodo medio (ms)",   lambda m: fmt(m["avg_period_ms"], decimals=3)))
    print(row("Periodo min (ms)",     lambda m: fmt(m["min_period_ms"], decimals=3)))
    print(row("Periodo max (ms)",     lambda m: fmt(m["max_period_ms"], decimals=3)))
    print(row("Deadline Miss (%)",    lambda m: fmt(m["miss_rate_pct"], decimals=2)))
    print(row("Deadline Misses (n)",  lambda m: str(m["deadline_misses"])))
    print(row("N pulsos",             lambda m: str(m["n_pulses"])))

    print(hdr)
    dl_str = "  ".join(f"CH{i}={d}ms" for i, d in enumerate(deadlines_ms))
    print(f"\nDeadlines: {dl_str}")
    print()


def main():
    args = parse_args()

    try:
        deadlines_ms = [float(d) for d in args.deadline.split(",")]
    except ValueError:
        print("Erro: --deadline deve ser 4 numeros separados por virgula.", file=sys.stderr)
        sys.exit(1)
    if len(deadlines_ms) != 4:
        print("Erro: fornecer exatamente 4 deadlines.", file=sys.stderr)
        sys.exit(1)

    try:
        fieldnames, rows = load_csv(args.csv_file)
    except FileNotFoundError:
        print(f"Arquivo nao encontrado: {args.csv_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro ao ler CSV: {e}", file=sys.stderr)
        sys.exit(1)

    if not fieldnames:
        print("CSV sem cabecalho reconhecido.", file=sys.stderr)
        sys.exit(1)

    # Coluna de tempo
    time_col = find_column(fieldnames, ["time"])
    if time_col is None:
        print("Coluna de tempo nao encontrada.", file=sys.stderr)
        sys.exit(1)

    all_metrics = []
    for i in range(4):
        col = find_column(fieldnames, [f"channel {i}", f"ch{i}", f"channel{i}"])
        if col is None:
            print(f"Aviso: canal {i} nao encontrado no CSV.", file=sys.stderr)
            all_metrics.append(None)
            continue

        edges = build_edges(rows, time_col, col)
        n_rising = sum(1 for _, e in edges if e == "rising")
        if n_rising < args.min_pulses:
            print(f"Aviso: CH{i} tem apenas {n_rising} pulsos (minimo: {args.min_pulses}).", file=sys.stderr)

        m = compute_metrics(edges, deadlines_ms[i])
        all_metrics.append(m)

    print_table(all_metrics, deadlines_ms)


if __name__ == "__main__":
    main()
