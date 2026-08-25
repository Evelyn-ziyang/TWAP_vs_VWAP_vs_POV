"""Generate the four README-style TWAP/VWAP/POV figures.

The composition follows the figure sequence in the reference README while the
numbers come from this repository's AAPL fixture and execution model.  Both PNG
and SVG are emitted without matplotlib so the script remains usable in the
project's current environment.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from html import escape
import math
from pathlib import Path
from statistics import fmean, median, pstdev
import sys
from typing import Iterable, Sequence

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from algo_exec import (  # noqa: E402
    BacktestResult,
    ExecutionConfig,
    build_volume_profile,
    load_dataset,
    pov,
    simulate_execution,
    twap,
    vwap,
)
from generate_algo_comparison import font  # noqa: E402


OUT_DIR = ROOT / "figures" / "readme"
BACKGROUND = "#FFFFFF"
FOREGROUND = "#263238"
MUTED = "#66727A"
GRID = "#DFE5E8"
TWAP_COLOR = "#4C78A8"
VWAP_COLOR = "#F58518"
POV_COLOR = "#54A24B"
VOLUME_COLOR = "#C9D7E5"
CAP_COLOR = "#D65F4A"
GREEN = "#4F8F5B"
RED = "#C65B4B"
YELLOW = "#FFF0B3"
LIGHT_GREEN = "#B9DCA7"
LIGHT_RED = "#E9A08F"
SERIES = {
    "TWAP": TWAP_COLOR,
    "Forecast VWAP": VWAP_COLOR,
    "POV": POV_COLOR,
}
ORDER_FRACTION = 0.03


@dataclass(frozen=True)
class WindowObservation:
    session: str
    start_slot: str
    end_slot: str
    volume: float
    target_qty: int
    realized_volatility: float
    twap_is_bps: float
    vwap_is_bps: float
    pov_is_bps: float
    twap_fill: float
    vwap_fill: float
    pov_fill: float

    @property
    def vwap_delta_bps(self) -> float:
        return self.vwap_is_bps - self.twap_is_bps

    @property
    def pov_delta_bps(self) -> float:
        return self.pov_is_bps - self.twap_is_bps


class Canvas:
    """Draw once to a Pillow bitmap and a structurally equivalent SVG."""

    def __init__(self, width: int, height: int, title: str, desc: str) -> None:
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height), BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.svg: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f"<title>{escape(title)}</title>",
            f"<desc>{escape(desc)}</desc>",
            f'<rect width="{width}" height="{height}" fill="{BACKGROUND}"/>',
        ]

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: int = 20,
        *,
        bold: bool = False,
        fill: str = FOREGROUND,
        anchor: str = "lt",
    ) -> None:
        chosen = font(size, bold=bold)
        self.draw.text((x, y), value, font=chosen, fill=fill, anchor=anchor)
        h_anchor = {"l": "start", "m": "middle", "r": "end"}[anchor[0]]
        v_anchor = {
            "t": "hanging",
            "m": "middle",
            "a": "auto",
            "b": "text-after-edge",
        }.get(anchor[1], "hanging")
        weight = 700 if bold else 400
        self.svg.append(
            f'<text x="{x:.2f}" y="{y:.2f}" fill="{fill}" font-family="Arial, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{h_anchor}" '
            f'dominant-baseline="{v_anchor}">{escape(value)}</text>'
        )

    def line(
        self,
        points: Sequence[tuple[float, float]],
        *,
        fill: str,
        width: int = 2,
        dash: tuple[int, int] | None = None,
    ) -> None:
        if len(points) < 2:
            return
        if dash is None:
            self.draw.line(points, fill=fill, width=width, joint="curve")
        else:
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                length = math.hypot(x1 - x0, y1 - y0)
                if length == 0:
                    continue
                ux, uy = (x1 - x0) / length, (y1 - y0) / length
                cursor = 0.0
                while cursor < length:
                    end = min(cursor + dash[0], length)
                    self.draw.line(
                        (x0 + ux * cursor, y0 + uy * cursor, x0 + ux * end, y0 + uy * end),
                        fill=fill,
                        width=width,
                    )
                    cursor += dash[0] + dash[1]
        point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        dash_attr = f' stroke-dasharray="{dash[0]} {dash[1]}"' if dash else ""
        element = "polyline" if len(points) > 2 else "line"
        if element == "polyline":
            self.svg.append(
                f'<polyline points="{point_text}" fill="none" stroke="{fill}" stroke-width="{width}" '
                f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>'
            )
        else:
            (x0, y0), (x1, y1) = points
            self.svg.append(
                f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" '
                f'stroke="{fill}" stroke-width="{width}" stroke-linecap="round"{dash_attr}/>'
            )

    def rect(
        self,
        box: tuple[float, float, float, float],
        *,
        fill: str,
        outline: str | None = None,
        width: int = 1,
    ) -> None:
        self.draw.rectangle(box, fill=fill, outline=outline, width=width)
        x0, y0, x1, y1 = box
        stroke = f' stroke="{outline}" stroke-width="{width}"' if outline else ""
        self.svg.append(
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1-x0:.2f}" height="{y1-y0:.2f}" fill="{fill}"{stroke}/>'
        )

    def circle(self, x: float, y: float, radius: float, *, fill: str, outline: str = BACKGROUND) -> None:
        self.draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=outline, width=2)
        self.svg.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{fill}" stroke="{outline}" stroke-width="2"/>'
        )

    def polygon(self, points: Sequence[tuple[float, float]], *, fill: str, outline: str | None = None) -> None:
        self.draw.polygon(points, fill=fill, outline=outline)
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        stroke = f' stroke="{outline}" stroke-width="1"' if outline else ""
        self.svg.append(f'<polygon points="{pts}" fill="{fill}"{stroke}/>')

    def save(self, stem: str) -> tuple[Path, Path]:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        png = OUT_DIR / f"{stem}.png"
        svg = OUT_DIR / f"{stem}.svg"
        self.image.save(png, format="PNG", optimize=True)
        self.svg.append("</svg>")
        svg.write_text("\n".join(self.svg) + "\n", encoding="utf-8")
        return png, svg


def group_sessions(records: Iterable[dict]) -> dict[str, list[dict]]:
    sessions: dict[str, list[dict]] = {}
    for record in records:
        sessions.setdefault(str(record["session"]), []).append(record)
    for bars in sessions.values():
        bars.sort(key=lambda row: row["timestamp"])
    return sessions


def schedules_for_bars(training: Sequence[dict], bars: Sequence[dict], config: ExecutionConfig) -> dict[str, list[int]]:
    profile = build_volume_profile(training, bars)
    return {
        "TWAP": twap(config.total_qty, len(bars), config.lot_size),
        "Forecast VWAP": vwap(config.total_qty, profile, config.lot_size),
        "POV": pov(
            config.total_qty,
            [float(bar["volume"]) for bar in bars],
            config.pov_rate,
            config.lot_size,
        ),
    }


def dynamic_window_config(bars: Sequence[dict], *, order_fraction: float = ORDER_FRACTION) -> ExecutionConfig:
    """Size a research parent order as a fixed fraction of realized window volume."""
    lot_size = 1
    window_volume = sum(float(bar["volume"]) for bar in bars)
    units = math.floor(window_volume * order_fraction / lot_size)
    total_qty = max(lot_size, units * lot_size)
    return ExecutionConfig(total_qty=total_qty, lot_size=lot_size)


def results_for_bars(
    bars: Sequence[dict], schedules: dict[str, list[int]], config: ExecutionConfig
) -> dict[str, BacktestResult]:
    return {
        name: simulate_execution(name, schedule, bars, config)
        for name, schedule in schedules.items()
    }


def executed_per_bar(result: BacktestResult, bars: Sequence[dict]) -> list[int]:
    by_stamp = {fill.timestamp: fill.qty for fill in result.fills}
    return [by_stamp.get(str(bar["timestamp"]), 0) for bar in bars]


def cumulative(values: Sequence[int]) -> list[int]:
    output: list[int] = []
    running = 0
    for value in values:
        running += value
        output.append(running)
    return output


def rolling_window_observations() -> list[WindowObservation]:
    dataset = load_dataset(ROOT / "Data_example" / "example.pkl")
    by_session = group_sessions(dataset["records"])
    session_names = sorted(by_session)
    observations: list[WindowObservation] = []
    window_bars = 12
    step = 3
    for test_index in range(1, len(session_names)):
        current_session = session_names[test_index]
        training = [
            bar
            for session in session_names[:test_index]
            for bar in by_session[session]
        ]
        session_bars = by_session[current_session]
        for start in range(0, len(session_bars) - window_bars + 1, step):
            bars = session_bars[start : start + window_bars]
            config = dynamic_window_config(bars)
            schedules = schedules_for_bars(training, bars, config)
            results = results_for_bars(bars, schedules, config)
            closes = [float(bar["close"]) for bar in bars]
            returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            observations.append(
                WindowObservation(
                    session=current_session,
                    start_slot=str(bars[0]["slot"]),
                    end_slot=str(bars[-1]["slot"]),
                    volume=sum(float(bar["volume"]) for bar in bars),
                    target_qty=config.total_qty,
                    realized_volatility=pstdev(returns) if len(returns) > 1 else 0.0,
                    twap_is_bps=results["TWAP"].arrival_shortfall_bps,
                    vwap_is_bps=results["Forecast VWAP"].arrival_shortfall_bps,
                    pov_is_bps=results["POV"].arrival_shortfall_bps,
                    twap_fill=results["TWAP"].completion_rate,
                    vwap_fill=results["Forecast VWAP"].completion_rate,
                    pov_fill=results["POV"].completion_rate,
                )
            )
    return observations


def write_observations(observations: Sequence[WindowObservation]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "rolling_window_results.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "session",
                "start_slot",
                "end_slot",
                "window_volume",
                "target_qty",
                "order_fraction",
                "realized_volatility",
                "twap_is_bps",
                "forecast_vwap_is_bps",
                "pov_is_bps",
                "twap_fill",
                "forecast_vwap_fill",
                "pov_fill",
                "forecast_vwap_minus_twap_bps",
                "pov_minus_twap_bps",
            ]
        )
        for obs in observations:
            writer.writerow(
                [
                    obs.session,
                    obs.start_slot,
                    obs.end_slot,
                    f"{obs.volume:.6f}",
                    str(obs.target_qty),
                    f"{ORDER_FRACTION:.6f}",
                    f"{obs.realized_volatility:.10f}",
                    f"{obs.twap_is_bps:.6f}",
                    f"{obs.vwap_is_bps:.6f}",
                    f"{obs.pov_is_bps:.6f}",
                    f"{obs.twap_fill:.6f}",
                    f"{obs.vwap_fill:.6f}",
                    f"{obs.pov_fill:.6f}",
                    f"{obs.vwap_delta_bps:.6f}",
                    f"{obs.pov_delta_bps:.6f}",
                ]
            )
    return output


def marker(canvas: Canvas, x: float, y: float, name: str, radius: int = 6) -> None:
    color = SERIES[name]
    if name == "Forecast VWAP":
        canvas.rect((x - radius, y - radius, x + radius, y + radius), fill=color, outline=BACKGROUND, width=2)
    elif name == "POV":
        canvas.polygon(((x, y - radius - 1), (x - radius - 1, y + radius), (x + radius + 1, y + radius)), fill=color, outline=BACKGROUND)
    else:
        canvas.circle(x, y, radius, fill=color)


def series_legend(canvas: Canvas, x: float, y: float, *, compact: bool = False) -> None:
    spacing = 235 if compact else 265
    for index, name in enumerate(SERIES):
        xx = x + index * spacing
        canvas.line(((xx, y + 11), (xx + 42, y + 11)), fill=SERIES[name], width=5)
        marker(canvas, xx + 21, y + 11, name, 5)
        canvas.text(xx + 54, y, name, 18)


def plot_axes(
    canvas: Canvas,
    box: tuple[float, float, float, float],
    y_min: float,
    y_max: float,
    y_ticks: Sequence[float],
    x_labels: Sequence[str],
    *,
    percent: bool = False,
    currency: bool = False,
    categorical: bool = False,
) -> tuple:
    x0, y0, x1, y1 = box
    if categorical:
        to_x = lambda i: x0 + (i + 0.5) * (x1 - x0) / max(1, len(x_labels))
    else:
        to_x = lambda i: x0 + i * (x1 - x0) / max(1, len(x_labels) - 1)
    to_y = lambda v: y1 - (v - y_min) * (y1 - y0) / max(1e-12, y_max - y_min)
    for tick in y_ticks:
        yy = to_y(tick)
        canvas.line(((x0, yy), (x1, yy)), fill=GRID, width=2)
        label = f"{tick:.0f}%" if percent else (f"${tick:.2f}" if currency else f"{tick:.0f}")
        canvas.text(x0 - 14, yy, label, 17, fill=MUTED, anchor="rm")
    tick_indexes = sorted({0, len(x_labels) - 1, *(range(0, len(x_labels), max(1, len(x_labels) // 6)))})
    for index in tick_indexes:
        xx = to_x(index)
        canvas.line(((xx, y0), (xx, y1)), fill=GRID, width=2)
        canvas.text(xx, y1 + 17, x_labels[index], 17, fill=MUTED, anchor="mt")
    canvas.line(((x0, y0), (x0, y1)), fill=MUTED, width=2)
    canvas.line(((x0, y1), (x1, y1)), fill=MUTED, width=2)
    return to_x, to_y


def draw_summary_table(
    canvas: Canvas,
    x: float,
    y: float,
    widths: Sequence[float],
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    header_height = 58
    row_height = 68
    total_width = sum(widths)
    canvas.rect((x, y, x + total_width, y + header_height), fill="#EEF2F4")
    cursor = x
    for header, width in zip(headers, widths):
        canvas.text(cursor + width / 2, y + header_height / 2, header, 18, bold=True, anchor="mm")
        cursor += width
    current_y = y + header_height
    for row_index, row in enumerate(rows):
        canvas.rect(
            (x, current_y, x + total_width, current_y + row_height),
            fill="#F8FAFB" if row_index % 2 else BACKGROUND,
        )
        cursor = x
        for cell_index, (cell, width) in enumerate(zip(row, widths)):
            canvas.text(
                cursor + width / 2,
                current_y + row_height / 2,
                cell,
                18,
                bold=cell_index == 0,
                anchor="mm",
            )
            cursor += width
        current_y += row_height
    for line_index in range(len(rows) + 2):
        yy = y if line_index == 0 else y + header_height + (line_index - 1) * row_height
        canvas.line(((x, yy), (x + total_width, yy)), fill=GRID, width=2)


def render_full_day_case_study() -> tuple[Path, Path, dict[str, BacktestResult]]:
    dataset = load_dataset(ROOT / "Data_example" / "example.pkl")
    by_session = group_sessions(dataset["records"])
    sessions = sorted(by_session)
    training = [bar for session in sessions[:-1] for bar in by_session[session]]
    bars = by_session[sessions[-1]]
    config = ExecutionConfig()
    schedules = schedules_for_bars(training, bars, config)
    results = results_for_bars(bars, schedules, config)
    executed = {name: executed_per_bar(result, bars) for name, result in results.items()}
    labels = [str(bar["slot"]) for bar in bars]
    marker_indexes = sorted({0, len(labels) - 1, *range(0, len(labels), 13)})

    canvas = Canvas(
        1600,
        2200,
        "Full-day fixed-Q execution case study",
        "AAPL full-day comparison of market volume, target schedules, cumulative completion, price path, and outcome metrics for TWAP, Forecast VWAP, and POV.",
    )
    canvas.text(70, 40, "Full-day fixed-Q case study — AAPL", 46, bold=True)
    canvas.text(
        72,
        100,
        f"{sessions[-1]} • 09:30–16:00 ET • BUY {config.total_qty:,} shares • 5-minute bars • POV={config.pov_rate:.0%} • hard cap={config.max_participation_rate:.0%}",
        22,
        fill=MUTED,
    )

    # Market volume.
    canvas.text(70, 155, "Market volume and executable capacity", 28, bold=True)
    canvas.text(70, 191, "Provider-defined volume units", 17, fill=MUTED)
    volume_box = (140, 220, 1540, 485)
    volumes = [float(bar["volume"]) for bar in bars]
    max_volume = max(500, math.ceil(max(volumes) / 500) * 500)
    to_x, to_y = plot_axes(
        canvas,
        volume_box,
        0,
        max_volume,
        [0, max_volume / 2, max_volume],
        labels,
        categorical=True,
    )
    bar_width = (volume_box[2] - volume_box[0]) / len(labels) * 0.78
    for index, value in enumerate(volumes):
        xx = to_x(index)
        canvas.rect((xx - bar_width / 2, to_y(value), xx + bar_width / 2, to_y(0)), fill=VOLUME_COLOR)
    cap_points = [(to_x(i), to_y(value * config.max_participation_rate)) for i, value in enumerate(volumes)]
    canvas.line(cap_points, fill=CAP_COLOR, width=3, dash=(8, 6))
    canvas.rect((1120, 162, 1144, 182), fill=VOLUME_COLOR)
    canvas.text(1156, 162, "Market volume", 17)
    canvas.line(((1335, 173), (1378, 173)), fill=CAP_COLOR, width=3, dash=(8, 6))
    canvas.text(1390, 162, "20% cap", 17)

    # Target schedules.
    canvas.text(70, 550, "Target schedule per bar", 28, bold=True)
    canvas.text(70, 586, "New child-order target before carry and hard cap", 17, fill=MUTED)
    series_legend(canvas, 820, 550, compact=True)
    schedule_box = (140, 620, 1540, 885)
    max_schedule = max(max(values) for values in schedules.values())
    schedule_max = max(100, math.ceil(max_schedule / 100) * 100)
    to_x, to_y = plot_axes(canvas, schedule_box, 0, schedule_max, [0, schedule_max / 2, schedule_max], labels)
    for name in SERIES:
        points = [(to_x(i), to_y(value)) for i, value in enumerate(schedules[name])]
        canvas.line(points, fill=SERIES[name], width=5)
        for index in marker_indexes:
            marker(canvas, points[index][0], points[index][1], name, 5)

    # Cumulative actual fills.
    canvas.text(70, 955, "Cumulative completion", 28, bold=True)
    canvas.text(70, 991, "Actual fills after carry and the 20% per-bar hard cap", 17, fill=MUTED)
    series_legend(canvas, 820, 955, compact=True)
    cumulative_box = (140, 1025, 1540, 1290)
    to_x, to_y = plot_axes(canvas, cumulative_box, 0, 100, [0, 25, 50, 75, 100], labels, percent=True)
    canvas.line(((cumulative_box[0], to_y(100)), (cumulative_box[2], to_y(100))), fill=MUTED, width=2, dash=(9, 7))
    for name in SERIES:
        values = [100 * value / config.total_qty for value in cumulative(executed[name])]
        points = [(to_x(i), to_y(value)) for i, value in enumerate(values)]
        canvas.line(points, fill=SERIES[name], width=5)
        for index in marker_indexes:
            marker(canvas, points[index][0], points[index][1], name, 5)

    # Price path.
    canvas.text(70, 1360, "Price path over the execution window", 28, bold=True)
    canvas.text(70, 1396, "Bar close price (USD)", 17, fill=MUTED)
    prices = [float(bar["close"]) for bar in bars]
    arrival = float(bars[0]["open"])
    p_min = min(prices + [arrival])
    p_max = max(prices + [arrival])
    padding = max(0.25, (p_max - p_min) * 0.10)
    low, high = p_min - padding, p_max + padding
    price_box = (140, 1430, 1540, 1695)
    to_x, to_y = plot_axes(canvas, price_box, low, high, [low, (low + high) / 2, high], labels, currency=True)
    points = [(to_x(i), to_y(value)) for i, value in enumerate(prices)]
    canvas.line(points, fill="#333333", width=4)
    for index in marker_indexes:
        canvas.rect((points[index][0] - 4, points[index][1] - 4, points[index][0] + 4, points[index][1] + 4), fill="#333333")
    canvas.line(((price_box[0], to_y(arrival)), (price_box[2], to_y(arrival))), fill=CAP_COLOR, width=2, dash=(10, 7))
    canvas.text(price_box[2] - 8, to_y(arrival) - 10, f"Arrival ${arrival:.2f}", 17, fill=CAP_COLOR, anchor="rb")

    # Outcome table.
    canvas.text(70, 1780, "Single-session outcome", 28, bold=True)
    rows = []
    for name in SERIES:
        result = results[name]
        rows.append(
            [
                name,
                f"{result.completion_rate:.1%}",
                f"${result.average_execution_price:.4f}",
                f"{result.vwap_slippage_bps:+.2f} bps",
                f"${result.total_modelled_cost:.2f}",
            ]
        )
    draw_summary_table(
        canvas,
        140,
        1825,
        [270, 220, 270, 280, 260],
        ["Algorithm", "Completion", "Average price", "VWAP slippage", "Modelled cost"],
        rows,
    )
    canvas.text(
        70,
        2152,
        "Single-session illustration only; lower side-aware slippage is better. Current volume is provider-defined tick volume.",
        17,
        fill=MUTED,
    )
    png, svg = canvas.save("00_full_day_case_study")
    return png, svg, results


def render_single_window() -> tuple[Path, Path]:
    dataset = load_dataset(ROOT / "Data_example" / "example.pkl")
    by_session = group_sessions(dataset["records"])
    sessions = sorted(by_session)
    training = [bar for session in sessions[:-1] for bar in by_session[session]]
    bars = by_session[sessions[-1]][:12]
    config = dynamic_window_config(bars)
    schedules = schedules_for_bars(training, bars, config)
    results = results_for_bars(bars, schedules, config)
    executed = {name: executed_per_bar(result, bars) for name, result in results.items()}
    labels = [str(bar["slot"]) for bar in bars]

    canvas = Canvas(
        1600,
        1940,
        "Single-window execution demo",
        "AAPL 60-minute comparison of TWAP, forecast VWAP, and POV schedules, cumulative fills, market volume, and price.",
    )
    canvas.text(70, 42, "Single-window execution demo — AAPL", 46, bold=True)
    canvas.text(
        72,
        103,
        f"BUY Q={config.total_qty:,} ({ORDER_FRACTION:.0%} of window volume) • {labels[0]}–{labels[-1]} ET • ρPOV={config.pov_rate:.0%} • hard cap={config.max_participation_rate:.0%}",
        23,
        fill=MUTED,
    )

    # Panel 1: market volume and hard capacity.
    canvas.text(70, 162, "Market volume and executable capacity", 28, bold=True)
    canvas.text(70, 198, "Provider-defined volume units", 17, fill=MUTED)
    volume_box = (140, 225, 1540, 510)
    volumes = [float(bar["volume"]) for bar in bars]
    max_volume = math.ceil(max(volumes) / 500) * 500
    to_x, to_y = plot_axes(
        canvas,
        volume_box,
        0,
        max_volume,
        [0, max_volume / 2, max_volume],
        labels,
        categorical=True,
    )
    bar_width = (volume_box[2] - volume_box[0]) / len(bars) * 0.64
    for index, value in enumerate(volumes):
        xx = to_x(index)
        canvas.rect((xx - bar_width / 2, to_y(value), xx + bar_width / 2, to_y(0)), fill=VOLUME_COLOR)
    cap_values = [value * config.max_participation_rate for value in volumes]
    cap_points = [(to_x(i), to_y(value)) for i, value in enumerate(cap_values)]
    canvas.line(cap_points, fill=CAP_COLOR, width=3, dash=(8, 6))
    canvas.rect((1180, 170, 1204, 190), fill=VOLUME_COLOR)
    canvas.text(1216, 170, "Market volume", 17)
    canvas.line(((1360, 181), (1400, 181)), fill=CAP_COLOR, width=3, dash=(8, 6))
    canvas.text(1412, 170, "20% cap", 17)

    # Panel 2: executed shares.
    canvas.text(70, 580, "Executed shares per bar", 28, bold=True)
    series_legend(canvas, 820, 580, compact=True)
    schedule_box = (140, 635, 1540, 910)
    max_exec = max(max(values) for values in executed.values())
    y_max = math.ceil(max(100, max_exec) / 50) * 50
    to_x, to_y = plot_axes(
        canvas,
        schedule_box,
        0,
        y_max,
        [0, y_max / 2, y_max],
        labels,
        categorical=True,
    )
    group_width = (schedule_box[2] - schedule_box[0]) / len(labels) * 0.72
    one_width = group_width / 3
    for index in range(len(labels)):
        center = to_x(index)
        for j, name in enumerate(SERIES):
            value = executed[name][index]
            left = center - group_width / 2 + j * one_width
            canvas.rect((left, to_y(value), left + one_width - 2, to_y(0)), fill=SERIES[name])
    twap_target = config.total_qty / len(labels)
    canvas.line(((schedule_box[0], to_y(twap_target)), (schedule_box[2], to_y(twap_target))), fill=MUTED, width=2, dash=(8, 6))
    canvas.text(schedule_box[2] - 8, to_y(twap_target) - 10, f"TWAP target ≈ {twap_target:.0f}", 16, fill=MUTED, anchor="rb")

    # Panel 3: cumulative fills.
    canvas.text(70, 990, "Cumulative fill progress", 28, bold=True)
    canvas.text(70, 1026, "Percent of parent quantity", 17, fill=MUTED)
    series_legend(canvas, 820, 990, compact=True)
    cum_box = (140, 1050, 1540, 1325)
    to_x, to_y = plot_axes(canvas, cum_box, 0, 100, [0, 25, 50, 75, 100], labels, percent=True)
    canvas.line(((cum_box[0], to_y(100)), (cum_box[2], to_y(100))), fill=MUTED, width=2, dash=(9, 7))
    for name in SERIES:
        values = [100 * value / config.total_qty for value in cumulative(executed[name])]
        points = [(to_x(i), to_y(value)) for i, value in enumerate(values)]
        canvas.line(points, fill=SERIES[name], width=5)
        for i, (xx, yy) in enumerate(points):
            if i in (0, 3, 6, 9, 11):
                marker(canvas, xx, yy, name, 5)
        label_offsets = {"TWAP": -42, "Forecast VWAP": -18, "POV": 14}
        canvas.text(
            points[-1][0] - 8,
            points[-1][1] + label_offsets[name],
            f"{values[-1]:.1f}%",
            17,
            bold=True,
            fill=FOREGROUND,
            anchor="rb",
        )

    # Panel 4: price path.
    canvas.text(70, 1400, "Price path over execution window", 28, bold=True)
    canvas.text(70, 1436, "Bar close price (USD)", 17, fill=MUTED)
    prices = [float(bar["close"]) for bar in bars]
    arrival = float(bars[0]["open"])
    p_min = min(prices + [arrival])
    p_max = max(prices + [arrival])
    padding = max(0.25, (p_max - p_min) * 0.15)
    low, high = p_min - padding, p_max + padding
    price_box = (140, 1460, 1540, 1735)
    price_ticks = [low, (low + high) / 2, high]
    to_x, to_y = plot_axes(canvas, price_box, low, high, price_ticks, labels, currency=True)
    price_points = [(to_x(i), to_y(value)) for i, value in enumerate(prices)]
    canvas.line(price_points, fill="#333333", width=4)
    for xx, yy in price_points:
        canvas.rect((xx - 4, yy - 4, xx + 4, yy + 4), fill="#333333")
    canvas.line(((price_box[0], to_y(arrival)), (price_box[2], to_y(arrival))), fill=CAP_COLOR, width=2, dash=(10, 7))
    canvas.text(price_box[2] - 8, to_y(arrival) - 10, f"Arrival ${arrival:.2f}", 17, fill=CAP_COLOR, anchor="rb")

    completion = " • ".join(f"{name} {results[name].completion_rate:.1%}" for name in SERIES)
    canvas.text(70, 1840, f"Window completion: {completion}", 19, bold=True)
    canvas.text(70, 1880, "Research normalization uses realized window volume ex post; fixture volume is provider-defined tick volume.", 17, fill=MUTED)
    return canvas.save("01_single_window_demo")


def histogram(values: Sequence[float], edges: Sequence[float]) -> list[int]:
    counts = [0] * (len(edges) - 1)
    for value in values:
        if value == edges[-1]:
            counts[-1] += 1
            continue
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]:
                counts[index] += 1
                break
    return counts


def render_delta_histograms(observations: Sequence[WindowObservation]) -> tuple[Path, Path]:
    deltas = {
        "Forecast VWAP − TWAP": [obs.vwap_delta_bps for obs in observations],
        "POV − TWAP": [obs.pov_delta_bps for obs in observations],
    }
    all_values = [value for values in deltas.values() for value in values]
    bound = max(abs(min(all_values)), abs(max(all_values))) * 1.05
    magnitude = 10 ** math.floor(math.log10(bound)) if bound > 0 else 1
    candidates = [magnitude, 2 * magnitude, 5 * magnitude, 10 * magnitude]
    bound = next(candidate for candidate in candidates if candidate >= bound)
    bins = 36
    edges = [-bound + 2 * bound * i / bins for i in range(bins + 1)]
    all_counts = [histogram(values, edges) for values in deltas.values()]
    count_max = max(max(counts) for counts in all_counts)
    y_max = max(5, math.ceil(count_max / 5) * 5)

    canvas = Canvas(
        1600,
        760,
        "Implementation-shortfall differences",
        "Rolling-window distributions of Forecast VWAP minus TWAP and POV minus TWAP implementation shortfall in basis points.",
    )
    canvas.text(70, 42, "Implementation-shortfall difference distributions", 42, bold=True)
    canvas.text(72, 97, f"AAPL • {len(observations)} overlapping 60-minute windows • Q = {ORDER_FRACTION:.0%} of each window's realized volume", 21, fill=MUTED)
    panel_boxes = [(95, 185, 770, 655), (890, 185, 1565, 655)]
    for panel_index, ((name, values), counts, box) in enumerate(zip(deltas.items(), all_counts, panel_boxes)):
        x0, y0, x1, y1 = box
        canvas.text(x0, 142, name, 25, bold=True)
        to_x = lambda value: x0 + (value + bound) * (x1 - x0) / (2 * bound)
        to_y = lambda value: y1 - value * (y1 - y0) / y_max
        for tick in (0, y_max / 2, y_max):
            yy = to_y(tick)
            canvas.line(((x0, yy), (x1, yy)), fill=GRID, width=2)
            canvas.text(x0 - 12, yy, f"{tick:.0f}", 17, fill=MUTED, anchor="rm")
        for tick in (-bound, -bound / 2, 0, bound / 2, bound):
            xx = to_x(tick)
            canvas.line(((xx, y0), (xx, y1)), fill=GRID, width=2)
            canvas.text(xx, y1 + 16, f"{tick:.0f}", 17, fill=MUTED, anchor="mt")
        canvas.line(((x0, y0), (x0, y1)), fill=MUTED, width=2)
        canvas.line(((x0, y1), (x1, y1)), fill=MUTED, width=2)
        for index, count in enumerate(counts):
            left, right = to_x(edges[index]), to_x(edges[index + 1])
            color = GREEN if edges[index] < 0 else RED
            canvas.rect((left + 1, to_y(count), right - 1, y1), fill=color)
        zero_x = to_x(0)
        canvas.line(((zero_x, y0), (zero_x, y1)), fill=FOREGROUND, width=2, dash=(8, 6))
        mean = fmean(values)
        mean_x = to_x(mean)
        canvas.line(((mean_x, y0), (mean_x, y1)), fill=SERIES["Forecast VWAP"] if panel_index == 0 else SERIES["POV"], width=4)
        win_rate = sum(value < 0 for value in values) / len(values)
        canvas.text(x0 + 18, y0 + 18, f"Mean ΔIS {mean:+.2f} bps", 18, bold=True)
        canvas.text(x0 + 18, y0 + 48, f"Win rate {win_rate:.1%}", 18, bold=True, fill=GREEN)
    canvas.text(800, 718, "ΔIS (basis points per executed share)", 18, fill=MUTED, anchor="mt")
    return canvas.save("02_delta_is_distribution")


def interpolate_color(low: str, high: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    lo = tuple(int(low[i : i + 2], 16) for i in (1, 3, 5))
    hi = tuple(int(high[i : i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(a + (b - a) * t) for a, b in zip(lo, hi))
    return "#" + "".join(f"{value:02X}" for value in rgb)


def regime_cells(
    observations: Sequence[WindowObservation],
    delta_attr: str,
) -> tuple[list[list[float]], list[list[float]], int]:
    volume_med = median(obs.volume for obs in observations)
    volatility_med = median(obs.realized_volatility for obs in observations)
    cells: list[list[list[WindowObservation]]] = [[[], []], [[], []]]
    for obs in observations:
        row = 1 if obs.volume >= volume_med else 0
        col = 1 if obs.realized_volatility >= volatility_med else 0
        cells[row][col].append(obs)
    means = [[0.0, 0.0], [0.0, 0.0]]
    rates = [[0.0, 0.0], [0.0, 0.0]]
    for row in range(2):
        for col in range(2):
            values = [float(getattr(obs, delta_attr)) for obs in cells[row][col]]
            means[row][col] = fmean(values) if values else math.nan
            rates[row][col] = sum(value < 0 for value in values) / len(values) if values else math.nan
    return means, rates, len(observations)


def draw_heatmap(
    canvas: Canvas,
    box: tuple[float, float, float, float],
    matrix: Sequence[Sequence[float]],
    *,
    title: str,
    value_type: str,
    scale: float,
) -> None:
    x0, y0, x1, y1 = box
    canvas.text((x0 + x1) / 2, y0 - 56, title, 23, bold=True, anchor="mt")
    cell_w = (x1 - x0) / 2
    cell_h = (y1 - y0) / 2
    for row in range(2):
        for col in range(2):
            value = matrix[row][col]
            if math.isnan(value):
                color = GRID
                label = "n/a"
            elif value_type == "delta":
                normalized = max(-1.0, min(1.0, value / scale))
                color = (
                    interpolate_color(YELLOW, LIGHT_GREEN, -normalized)
                    if normalized < 0
                    else interpolate_color(YELLOW, LIGHT_RED, normalized)
                )
                label = f"{value:+.2f} bps"
            else:
                normalized = max(-1.0, min(1.0, (value - 0.5) / 0.15))
                color = (
                    interpolate_color(YELLOW, LIGHT_RED, -normalized)
                    if normalized < 0
                    else interpolate_color(YELLOW, LIGHT_GREEN, normalized)
                )
                label = f"{value:.1%}"
            # Display low-volume row first (top) and high-volume second.
            top = y0 + row * cell_h
            left = x0 + col * cell_w
            canvas.rect((left, top, left + cell_w, top + cell_h), fill=color, outline=BACKGROUND, width=4)
            canvas.text(left + cell_w / 2, top + cell_h / 2, label, 24, bold=True, anchor="mm")
    canvas.text(x0 + cell_w / 2, y1 + 16, "Low vol", 17, fill=MUTED, anchor="mt")
    canvas.text(x0 + 1.5 * cell_w, y1 + 16, "High vol", 17, fill=MUTED, anchor="mt")
    canvas.text(x0 - 16, y0 + cell_h / 2, "Low volume", 17, fill=MUTED, anchor="rm")
    canvas.text(x0 - 16, y0 + 1.5 * cell_h, "High volume", 17, fill=MUTED, anchor="rm")


def render_regime_heatmap(observations: Sequence[WindowObservation]) -> tuple[Path, Path]:
    vwap_means, vwap_rates, _ = regime_cells(observations, "vwap_delta_bps")
    pov_means, pov_rates, _ = regime_cells(observations, "pov_delta_bps")
    finite_means = [
        abs(value)
        for matrix in (vwap_means, pov_means)
        for row in matrix
        for value in row
        if not math.isnan(value)
    ]
    scale = max(finite_means) or 1.0
    canvas = Canvas(
        1600,
        1080,
        "Regime analysis",
        "Mean implementation-shortfall differences and win rates for Forecast VWAP and POV across volume and realized-volatility regimes.",
    )
    canvas.text(70, 42, "Regime analysis: volume × realized volatility", 42, bold=True)
    canvas.text(72, 97, f"AAPL • {len(observations)} overlapping 60-minute windows • Q = {ORDER_FRACTION:.0%} of realized window volume • median splits", 21, fill=MUTED)
    draw_heatmap(canvas, (190, 215, 780, 485), vwap_means, title="Mean ΔIS vs TWAP", value_type="delta", scale=scale)
    draw_heatmap(canvas, (945, 215, 1535, 485), vwap_rates, title="Win rate vs TWAP", value_type="rate", scale=1)
    draw_heatmap(canvas, (190, 655, 780, 925), pov_means, title="Mean ΔIS vs TWAP", value_type="delta", scale=scale)
    draw_heatmap(canvas, (945, 655, 1535, 925), pov_rates, title="Win rate vs TWAP", value_type="rate", scale=1)
    canvas.text(45, 320, "Forecast", 23, bold=True)
    canvas.text(45, 350, "VWAP", 23, bold=True)
    canvas.text(45, 777, "POV", 24, bold=True)
    canvas.text(800, 1002, "Green indicates lower IS / higher win rate; negative ΔIS is better.", 18, fill=MUTED, anchor="mt")
    canvas.text(800, 1035, "Overlapping windows are descriptive observations, not independent statistical samples.", 17, fill=MUTED, anchor="mt")
    return canvas.save("03_regime_heatmap")


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def box_stats(values: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    q1, med, q3 = quantile(values, 0.25), quantile(values, 0.5), quantile(values, 0.75)
    iqr = q3 - q1
    lower_bound, upper_bound = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    lower = min(value for value in values if value >= lower_bound)
    upper = max(value for value in values if value <= upper_bound)
    return lower, q1, med, q3, upper, fmean(values)


def render_is_boxplots(observations: Sequence[WindowObservation]) -> tuple[Path, Path]:
    data = {
        "TWAP": [obs.twap_is_bps for obs in observations],
        "Forecast VWAP": [obs.vwap_is_bps for obs in observations],
        "POV": [obs.pov_is_bps for obs in observations],
    }
    all_stats = {name: box_stats(values) for name, values in data.items()}
    low = math.floor(min(stats[0] for stats in all_stats.values()) / 25) * 25
    high = math.ceil(max(stats[4] for stats in all_stats.values()) / 25) * 25
    if low == high:
        high = low + 100
    canvas = Canvas(
        1300,
        820,
        "Implementation shortfall by algorithm",
        "AAPL rolling-window implementation-shortfall distributions for TWAP, Forecast VWAP, and POV.",
    )
    canvas.text(65, 42, "Implementation shortfall distribution by algorithm", 40, bold=True)
    canvas.text(67, 95, f"AAPL • {len(observations)} overlapping 60-minute windows • Q = {ORDER_FRACTION:.0%} of realized window volume", 21, fill=MUTED)
    canvas.text(135, 143, "Arrival implementation shortfall (bps)", 18, fill=MUTED)
    box = (135, 175, 1235, 690)
    x0, y0, x1, y1 = box
    to_y = lambda value: y1 - (value - low) * (y1 - y0) / (high - low)
    ticks = [low + (high - low) * i / 4 for i in range(5)]
    for tick in ticks:
        yy = to_y(tick)
        canvas.line(((x0, yy), (x1, yy)), fill=GRID, width=2)
        canvas.text(x0 - 14, yy, f"{tick:.0f}", 17, fill=MUTED, anchor="rm")
    if low <= 0 <= high:
        canvas.line(((x0, to_y(0)), (x1, to_y(0))), fill=MUTED, width=2, dash=(9, 7))
    centers = [330, 685, 1040]
    for center, (name, values) in zip(centers, data.items()):
        lower, q1, med, q3, upper, mean = all_stats[name]
        color = SERIES[name]
        canvas.line(((center, to_y(lower)), (center, to_y(upper))), fill=FOREGROUND, width=3)
        canvas.line(((center - 42, to_y(lower)), (center + 42, to_y(lower))), fill=FOREGROUND, width=3)
        canvas.line(((center - 42, to_y(upper)), (center + 42, to_y(upper))), fill=FOREGROUND, width=3)
        canvas.rect((center - 88, to_y(q3), center + 88, to_y(q1)), fill=color, outline=FOREGROUND, width=2)
        canvas.line(((center - 88, to_y(med)), (center + 88, to_y(med))), fill=BACKGROUND, width=4)
        canvas.polygon(
            ((center, to_y(mean) - 8), (center - 8, to_y(mean)), (center, to_y(mean) + 8), (center + 8, to_y(mean))),
            fill=BACKGROUND,
            outline=color,
        )
        canvas.text(center, y1 + 22, name, 20, bold=True, anchor="mt")
        canvas.text(center, y1 + 56, f"mean {mean:+.1f} bps", 17, fill=MUTED, anchor="mt")
    canvas.text(65, 780, "Whiskers use 1.5×IQR; outliers are hidden. All three algorithms completed 100% in these normalized windows.", 17, fill=MUTED)
    return canvas.save("04_is_distribution_by_algorithm")


def render_completion_rate(observations: Sequence[WindowObservation]) -> tuple[Path, Path]:
    completion = {
        "TWAP": [obs.twap_fill for obs in observations],
        "Forecast VWAP": [obs.vwap_fill for obs in observations],
        "POV": [obs.pov_fill for obs in observations],
    }
    means = {name: fmean(values) for name, values in completion.items()}
    canvas = Canvas(
        1300,
        700,
        "Dynamic-Q completion rate",
        "Mean completion rate for TWAP, Forecast VWAP, and POV across normalized AAPL rolling windows.",
    )
    canvas.text(65, 42, "Dynamic-Q completion rate", 40, bold=True)
    canvas.text(
        67,
        95,
        f"AAPL • {len(observations)} overlapping 60-minute windows • Q = {ORDER_FRACTION:.0%} of realized window volume",
        21,
        fill=MUTED,
    )
    box = (135, 160, 1235, 565)
    x0, y0, x1, y1 = box
    to_y = lambda value: y1 - value * (y1 - y0)
    for tick in (0.0, 0.25, 0.50, 0.75, 1.0):
        yy = to_y(tick)
        canvas.line(((x0, yy), (x1, yy)), fill=GRID, width=2)
        canvas.text(x0 - 14, yy, f"{tick:.0%}", 17, fill=MUTED, anchor="rm")
    centers = [330, 685, 1040]
    bar_width = 180
    for center, name in zip(centers, SERIES):
        value = means[name]
        canvas.rect((center - bar_width / 2, to_y(value), center + bar_width / 2, y1), fill=SERIES[name])
        canvas.text(center, to_y(value) - 18, f"{value:.1%}", 22, bold=True, anchor="mb")
        canvas.text(center, y1 + 24, name, 20, bold=True, anchor="mt")
    canvas.text(
        65,
        652,
        "All algorithms completed every normalized window; ΔIS comparisons are therefore not driven by unequal completion.",
        17,
        fill=MUTED,
    )
    return canvas.save("05_completion_rate")


def write_full_day_summary(results: dict[str, BacktestResult]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "full_day_summary.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "algorithm",
                "completion_rate",
                "executed_qty",
                "average_execution_price",
                "arrival_shortfall_bps",
                "vwap_slippage_bps",
                "spread_cost",
                "impact_cost",
                "fees",
                "total_modelled_cost",
            ]
        )
        for name in SERIES:
            result = results[name]
            writer.writerow(
                [
                    name,
                    f"{result.completion_rate:.8f}",
                    result.executed_qty,
                    f"{result.average_execution_price:.8f}",
                    f"{result.arrival_shortfall_bps:.8f}",
                    f"{result.vwap_slippage_bps:.8f}",
                    f"{result.spread_cost:.8f}",
                    f"{result.impact_cost:.8f}",
                    f"{result.fees:.8f}",
                    f"{result.total_modelled_cost:.8f}",
                ]
            )
    return output


def write_dynamic_summary(observations: Sequence[WindowObservation]) -> Path:
    output = OUT_DIR / "dynamic_q_summary.csv"
    rows = {
        "TWAP": {
            "is": [obs.twap_is_bps for obs in observations],
            "fill": [obs.twap_fill for obs in observations],
            "delta": [0.0 for _ in observations],
        },
        "Forecast VWAP": {
            "is": [obs.vwap_is_bps for obs in observations],
            "fill": [obs.vwap_fill for obs in observations],
            "delta": [obs.vwap_delta_bps for obs in observations],
        },
        "POV": {
            "is": [obs.pov_is_bps for obs in observations],
            "fill": [obs.pov_fill for obs in observations],
            "delta": [obs.pov_delta_bps for obs in observations],
        },
    }
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "algorithm",
                "windows",
                "mean_is_bps",
                "median_is_bps",
                "mean_delta_vs_twap_bps",
                "median_delta_vs_twap_bps",
                "win_rate_vs_twap",
                "mean_completion_rate",
                "min_completion_rate",
                "max_completion_rate",
            ]
        )
        for name, values in rows.items():
            delta = values["delta"]
            win_rate = math.nan if name == "TWAP" else sum(value < 0 for value in delta) / len(delta)
            writer.writerow(
                [
                    name,
                    len(observations),
                    f"{fmean(values['is']):.8f}",
                    f"{median(values['is']):.8f}",
                    f"{fmean(delta):.8f}",
                    f"{median(delta):.8f}",
                    "" if math.isnan(win_rate) else f"{win_rate:.8f}",
                    f"{fmean(values['fill']):.8f}",
                    f"{min(values['fill']):.8f}",
                    f"{max(values['fill']):.8f}",
                ]
            )
    return output


def write_regime_summary(observations: Sequence[WindowObservation]) -> Path:
    output = OUT_DIR / "dynamic_q_regime_summary.csv"
    volume_med = median(obs.volume for obs in observations)
    volatility_med = median(obs.realized_volatility for obs in observations)
    comparisons = {
        "Forecast VWAP": ("vwap_delta_bps", "vwap_fill"),
        "POV": ("pov_delta_bps", "pov_fill"),
    }
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "algorithm",
                "volume_regime",
                "volatility_regime",
                "windows",
                "mean_delta_vs_twap_bps",
                "win_rate_vs_twap",
                "mean_completion_rate",
                "volume_median",
                "realized_volatility_median",
            ]
        )
        for name, (delta_attr, fill_attr) in comparisons.items():
            for volume_high in (False, True):
                for volatility_high in (False, True):
                    cell = [
                        obs
                        for obs in observations
                        if (obs.volume >= volume_med) == volume_high
                        and (obs.realized_volatility >= volatility_med) == volatility_high
                    ]
                    deltas = [float(getattr(obs, delta_attr)) for obs in cell]
                    fills = [float(getattr(obs, fill_attr)) for obs in cell]
                    writer.writerow(
                        [
                            name,
                            "High volume" if volume_high else "Low volume",
                            "High vol" if volatility_high else "Low vol",
                            len(cell),
                            f"{fmean(deltas):.8f}",
                            f"{sum(value < 0 for value in deltas) / len(deltas):.8f}",
                            f"{fmean(fills):.8f}",
                            f"{volume_med:.8f}",
                            f"{volatility_med:.10f}",
                        ]
                    )
    return output


def main() -> int:
    observations = rolling_window_observations()
    full_day_png, full_day_svg, full_day_results = render_full_day_case_study()
    outputs = [
        full_day_png,
        full_day_svg,
        write_full_day_summary(full_day_results),
        *render_single_window(),
        *render_delta_histograms(observations),
        *render_regime_heatmap(observations),
        *render_is_boxplots(observations),
        *render_completion_rate(observations),
        write_observations(observations),
        write_dynamic_summary(observations),
        write_regime_summary(observations),
    ]
    for path in outputs:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
