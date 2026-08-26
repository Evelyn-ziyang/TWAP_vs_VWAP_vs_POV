"""Generate presentation-ready TWAP/VWAP/POV comparison graphics.

Outputs both SVG and PNG from the repository's deterministic backtest fixture.
The implementation deliberately avoids matplotlib because the project runtime
may not have a NumPy-compatible matplotlib build.  PNG rendering uses Pillow;
SVG rendering uses the Python standard library.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algo_exec import (  # noqa: E402
    ExecutionConfig,
    build_volume_profile,
    load_dataset,
    pov,
    run_backtest,
    split_train_test,
    twap,
    vwap,
)


WIDTH = 1600
HEIGHT = 1860
BACKGROUND = "#FFFFFF"
FOREGROUND = "#263238"
MUTED = "#66727A"
GRID = "#E2E7EA"
HEADER = "#EEF2F4"
ROW_ALT = "#F8FAFB"
TWAP_COLOR = "#4C78A8"
VWAP_COLOR = "#F58518"
POV_COLOR = "#54A24B"
SERIES_COLORS = {"TWAP": TWAP_COLOR, "Forecast VWAP": VWAP_COLOR, "POV": POV_COLOR}


def _font_candidates(bold: bool = False) -> tuple[str, ...]:
    system_candidates = (
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    # Pillow commonly bundles DejaVu; the filename lookup is portable across
    # Windows, macOS, and Linux even when no system font path above exists.
    bundled_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return (bundled_name, *system_candidates)


def font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for candidate in _font_candidates(bold):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    # A missing presentation font should not make importing the algorithm or
    # collecting tests fail.  The bitmap fallback is less attractive but safe.
    return ImageFont.load_default()


FONTS = {
    "title": font(48, bold=True),
    "subtitle": font(25),
    "section": font(29, bold=True),
    "header": font(21, bold=True),
    "body": font(20),
    "axis": font(17),
    "foot": font(18),
}


def load_figure_data() -> dict[str, Any]:
    dataset = load_dataset(ROOT / "Data_example" / "example.pkl")
    training, test = split_train_test(dataset["records"])
    config = ExecutionConfig()
    profile = build_volume_profile(training, test)
    schedules = {
        "TWAP": twap(config.total_qty, len(test), config.lot_size),
        "Forecast VWAP": vwap(config.total_qty, profile, config.lot_size),
        "POV": pov(
            config.total_qty,
            [float(record["volume"]) for record in test],
            config.pov_rate,
            config.lot_size,
        ),
    }
    results = run_backtest(dataset, config)
    executed: dict[str, list[int]] = {}
    for display_name, result_name in (("TWAP", "TWAP"), ("Forecast VWAP", "VWAP"), ("POV", "POV")):
        by_timestamp = {fill.timestamp: fill.qty for fill in results[result_name].fills}
        executed[display_name] = [by_timestamp.get(record["timestamp"], 0) for record in test]
    return {
        "labels": [record["slot"] for record in test],
        "schedules": schedules,
        "executed": executed,
        "results": results,
        "config": config,
    }


def cumulative_percent(values: Sequence[int], total: int) -> list[float]:
    running = 0
    output: list[float] = []
    for value in values:
        running += value
        output.append(100.0 * running / total)
    return output


def wrap_text(draw: ImageDraw.ImageDraw, text: str, chosen_font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        width = draw.textbbox((0, 0), candidate, font=chosen_font)[2]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped_pil(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    chosen_font: ImageFont.FreeTypeFont,
    *,
    fill: str = FOREGROUND,
    bold: bool = False,
) -> None:
    left, top, right, bottom = box
    use_font = FONTS["header"] if bold else chosen_font
    lines = wrap_text(draw, text, use_font, right - left - 24)
    line_height = use_font.size + 6
    total_height = len(lines) * line_height
    y = top + max(8, (bottom - top - total_height) // 2)
    for line in lines:
        draw.text((left + 12, y), line, font=use_font, fill=fill)
        y += line_height


def draw_table_pil(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    widths: Sequence[int],
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    header_height: int,
    row_height: int,
) -> int:
    total_width = sum(widths)
    draw.rectangle((x, y, x + total_width, y + header_height), fill=HEADER)
    cursor_x = x
    for header, width in zip(headers, widths):
        draw_wrapped_pil(draw, (cursor_x, y, cursor_x + width, y + header_height), header, FONTS["header"], bold=True)
        cursor_x += width
    current_y = y + header_height
    for row_index, row in enumerate(rows):
        fill = ROW_ALT if row_index % 2 else BACKGROUND
        draw.rectangle((x, current_y, x + total_width, current_y + row_height), fill=fill)
        cursor_x = x
        for cell_index, (cell, width) in enumerate(zip(row, widths)):
            draw_wrapped_pil(
                draw,
                (cursor_x, current_y, cursor_x + width, current_y + row_height),
                cell,
                FONTS["body"],
                bold=cell_index == 0,
            )
            cursor_x += width
        current_y += row_height
    for row_line in range(len(rows) + 2):
        yy = y + header_height + max(0, row_line - 1) * row_height if row_line else y
        draw.line((x, yy, x + total_width, yy), fill=GRID, width=2)
    return current_y


def marker_pil(draw: ImageDraw.ImageDraw, x: float, y: float, color: str, shape: str) -> None:
    radius = 5
    if shape == "square":
        draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color, outline=BACKGROUND, width=2)
    elif shape == "triangle":
        draw.polygon(((x, y - 6), (x - 6, y + 5), (x + 6, y + 5)), fill=color, outline=BACKGROUND)
    else:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=BACKGROUND, width=2)


def draw_legend_pil(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    items = (("TWAP", "circle"), ("Forecast VWAP", "square"), ("POV", "triangle"))
    cursor = x
    for name, shape in items:
        color = SERIES_COLORS[name]
        draw.line((cursor, y + 11, cursor + 40, y + 11), fill=color, width=5)
        marker_pil(draw, cursor + 20, y + 11, color, shape)
        draw.text((cursor + 50, y), name, font=FONTS["axis"], fill=FOREGROUND)
        cursor += 215 if name != "Forecast VWAP" else 275


def chart_geometry(box: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    left, top, right, bottom = box
    return left + 78, top + 58, right - 28, bottom - 50


def draw_chart_pil(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    labels: Sequence[str],
    series: dict[str, Sequence[float]],
    y_ticks: Sequence[float],
    y_max: float,
    y_label: str,
    *,
    guide: float | None = None,
) -> None:
    left, top, right, bottom = box
    draw.text((left, top), title, font=FONTS["section"], fill=FOREGROUND)
    draw.text((left, top + 39), y_label, font=FONTS["axis"], fill=MUTED)
    draw_legend_pil(draw, right - 720, top + 5)
    x0, y0, x1, y1 = chart_geometry(box)
    plot_width = x1 - x0
    plot_height = y1 - y0
    x_coord = lambda index: x0 + index * plot_width / (len(labels) - 1)
    y_coord = lambda value: y1 - value * plot_height / y_max

    for tick in y_ticks:
        yy = y_coord(tick)
        draw.line((x0, yy, x1, yy), fill=GRID, width=2)
        label = f"{tick:.0f}%" if y_label.startswith("Percent") else f"{tick:.0f}"
        draw.text((x0 - 14, yy), label, font=FONTS["axis"], fill=MUTED, anchor="rm")
    x_tick_indexes = (0, 12, 24, 36, 48, 60, 72, 77)
    for index in x_tick_indexes:
        xx = x_coord(index)
        draw.line((xx, y0, xx, y1), fill=GRID, width=2)
        draw.text((xx, y1 + 15), labels[index], font=FONTS["axis"], fill=MUTED, anchor="ma")
    draw.line((x0, y0, x0, y1), fill=MUTED, width=2)
    draw.line((x0, y1, x1, y1), fill=MUTED, width=2)

    if guide is not None:
        yy = y_coord(guide)
        dash = 10
        xx = x0
        while xx < x1:
            draw.line((xx, yy, min(xx + dash, x1), yy), fill=MUTED, width=2)
            xx += dash * 2
        draw.text((x1, yy - 8), "100% parent", font=FONTS["axis"], fill=MUTED, anchor="ra")

    shapes = {"TWAP": "circle", "Forecast VWAP": "square", "POV": "triangle"}
    marker_indexes = (0, 12, 24, 36, 48, 60, 72, 77)
    for name, values in series.items():
        color = SERIES_COLORS[name]
        points = [(x_coord(index), y_coord(value)) for index, value in enumerate(values)]
        draw.line(points, fill=color, width=5, joint="curve")
        for index in marker_indexes:
            marker_pil(draw, points[index][0], points[index][1], color, shapes[name])


class SvgBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
            '<title>TWAP, forecast VWAP, and POV comparison</title>',
            '<desc>Decision table, per-bar targets, cumulative completion, and single-session outcome metrics.</desc>',
            f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        ]

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: int,
        fill: str = FOREGROUND,
        weight: int = 400,
        anchor: str = "start",
    ) -> None:
        self.add(
            f'<text x="{x}" y="{y}" fill="{fill}" font-family="Arial, Helvetica, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(content)}</text>'
        )

    def finish(self) -> str:
        return "\n".join([*self.parts, "</svg>", ""])


def svg_wrapped_text(
    svg: SvgBuilder,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    chosen_font: ImageFont.FreeTypeFont,
    *,
    bold: bool = False,
) -> None:
    left, top, right, bottom = box
    use_font = FONTS["header"] if bold else chosen_font
    lines = wrap_text(draw, text, use_font, right - left - 24)
    line_height = use_font.size + 6
    total_height = len(lines) * line_height
    y = top + max(8, (bottom - top - total_height) // 2) + use_font.size
    for line in lines:
        svg.text(left + 12, y, line, size=use_font.size, weight=700 if bold else 400)
        y += line_height


def draw_table_svg(
    svg: SvgBuilder,
    measure_draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    widths: Sequence[int],
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    header_height: int,
    row_height: int,
) -> int:
    total_width = sum(widths)
    svg.add(f'<rect x="{x}" y="{y}" width="{total_width}" height="{header_height}" fill="{HEADER}"/>')
    cursor_x = x
    for header, width in zip(headers, widths):
        svg_wrapped_text(svg, measure_draw, (cursor_x, y, cursor_x + width, y + header_height), header, FONTS["header"], bold=True)
        cursor_x += width
    current_y = y + header_height
    for row_index, row in enumerate(rows):
        fill = ROW_ALT if row_index % 2 else BACKGROUND
        svg.add(f'<rect x="{x}" y="{current_y}" width="{total_width}" height="{row_height}" fill="{fill}"/>')
        cursor_x = x
        for cell_index, (cell, width) in enumerate(zip(row, widths)):
            svg_wrapped_text(
                svg,
                measure_draw,
                (cursor_x, current_y, cursor_x + width, current_y + row_height),
                cell,
                FONTS["body"],
                bold=cell_index == 0,
            )
            cursor_x += width
        current_y += row_height
    horizontal_lines = [y, y + header_height, *[y + header_height + row_height * index for index in range(1, len(rows) + 1)]]
    for yy in horizontal_lines:
        svg.add(f'<line x1="{x}" y1="{yy}" x2="{x + total_width}" y2="{yy}" stroke="{GRID}" stroke-width="2"/>')
    return current_y


def svg_marker(svg: SvgBuilder, x: float, y: float, color: str, shape: str) -> None:
    if shape == "square":
        svg.add(f'<rect x="{x - 5:.2f}" y="{y - 5:.2f}" width="10" height="10" rx="1" fill="{color}" stroke="{BACKGROUND}" stroke-width="2"/>')
    elif shape == "triangle":
        points = f"{x:.2f},{y - 6:.2f} {x - 6:.2f},{y + 5:.2f} {x + 6:.2f},{y + 5:.2f}"
        svg.add(f'<polygon points="{points}" fill="{color}" stroke="{BACKGROUND}" stroke-width="2"/>')
    else:
        svg.add(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}" stroke="{BACKGROUND}" stroke-width="2"/>')


def draw_legend_svg(svg: SvgBuilder, x: int, y: int) -> None:
    items = (("TWAP", "circle"), ("Forecast VWAP", "square"), ("POV", "triangle"))
    cursor = x
    for name, shape in items:
        color = SERIES_COLORS[name]
        svg.add(f'<line x1="{cursor}" y1="{y + 11}" x2="{cursor + 40}" y2="{y + 11}" stroke="{color}" stroke-width="5"/>')
        svg_marker(svg, cursor + 20, y + 11, color, shape)
        svg.text(cursor + 50, y + 17, name, size=FONTS["axis"].size)
        cursor += 215 if name != "Forecast VWAP" else 275


def draw_chart_svg(
    svg: SvgBuilder,
    box: tuple[int, int, int, int],
    title: str,
    labels: Sequence[str],
    series: dict[str, Sequence[float]],
    y_ticks: Sequence[float],
    y_max: float,
    y_label: str,
    *,
    guide: float | None = None,
) -> None:
    left, top, right, bottom = box
    svg.text(left, top + 29, title, size=FONTS["section"].size, weight=700)
    svg.text(left, top + 59, y_label, size=FONTS["axis"].size, fill=MUTED)
    draw_legend_svg(svg, right - 720, top + 5)
    x0, y0, x1, y1 = chart_geometry(box)
    plot_width = x1 - x0
    plot_height = y1 - y0
    x_coord = lambda index: x0 + index * plot_width / (len(labels) - 1)
    y_coord = lambda value: y1 - value * plot_height / y_max
    for tick in y_ticks:
        yy = y_coord(tick)
        svg.add(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x1}" y2="{yy:.2f}" stroke="{GRID}" stroke-width="2"/>')
        label = f"{tick:.0f}%" if y_label.startswith("Percent") else f"{tick:.0f}"
        svg.text(x0 - 14, yy + 6, label, size=FONTS["axis"].size, fill=MUTED, anchor="end")
    x_tick_indexes = (0, 12, 24, 36, 48, 60, 72, 77)
    for index in x_tick_indexes:
        xx = x_coord(index)
        svg.add(f'<line x1="{xx:.2f}" y1="{y0}" x2="{xx:.2f}" y2="{y1}" stroke="{GRID}" stroke-width="2"/>')
        svg.text(xx, y1 + 32, labels[index], size=FONTS["axis"].size, fill=MUTED, anchor="middle")
    svg.add(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="{MUTED}" stroke-width="2"/>')
    svg.add(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{MUTED}" stroke-width="2"/>')
    if guide is not None:
        yy = y_coord(guide)
        svg.add(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x1}" y2="{yy:.2f}" stroke="{MUTED}" stroke-width="2" stroke-dasharray="10 10"/>')
        svg.text(x1, yy - 8, "100% parent", size=FONTS["axis"].size, fill=MUTED, anchor="end")
    shapes = {"TWAP": "circle", "Forecast VWAP": "square", "POV": "triangle"}
    marker_indexes = (0, 12, 24, 36, 48, 60, 72, 77)
    for name, values in series.items():
        color = SERIES_COLORS[name]
        points = [(x_coord(index), y_coord(value)) for index, value in enumerate(values)]
        point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        svg.add(f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')
        for index in marker_indexes:
            svg_marker(svg, points[index][0], points[index][1], color, shapes[name])


def figure_tables(data: dict[str, Any]) -> tuple[list[str], list[list[str]], list[str], list[list[str]]]:
    decision_headers = ["Algorithm", "Pacing signal", "Schedule known", "Completion", "Primary risk"]
    decision_rows = [
        ["TWAP", "Clock / equal time buckets", "Before start", "Target sum = Q", "Quiet-period over-participation"],
        ["Forecast VWAP", "Historical volume curve", "Before start", "Target sum = Q", "Forecast error on event days"],
        ["POV", "Realized-volume feedback", "Intraday / adaptive", "Residual allowed", "Uncertain finish; flow clustering"],
    ]
    metric_headers = ["Algorithm", "Completion", "Child orders", "Average price", "VWAP slippage", "Modelled cost"]
    metric_rows: list[list[str]] = []
    for display_name, result_name in (("TWAP", "TWAP"), ("Forecast VWAP", "VWAP"), ("POV", "POV")):
        result = data["results"][result_name]
        metric_rows.append(
            [
                display_name,
                f"{result.completion_rate:.1%}",
                str(result.child_orders),
                f"{result.average_execution_price:.4f}",
                f"{result.vwap_slippage_bps:.2f} bps",
                f"{result.total_modelled_cost:.2f}",
            ]
        )
    return decision_headers, decision_rows, metric_headers, metric_rows


def render_png(data: dict[str, Any], output: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), "TWAP vs Forecast VWAP vs POV", font=FONTS["title"], fill=FOREGROUND)
    draw.text((72, 104), "AAPL • BUY 5,000 shares • 5-minute bars • 2026-07-31", font=FONTS["subtitle"], fill=MUTED)
    decision_headers, decision_rows, metric_headers, metric_rows = figure_tables(data)
    draw_table_pil(
        draw,
        70,
        155,
        [220, 330, 250, 250, 410],
        decision_headers,
        decision_rows,
        header_height=62,
        row_height=96,
    )
    draw_chart_pil(
        draw,
        (70, 545, 1530, 950),
        "Per-bar target schedule",
        data["labels"],
        data["schedules"],
        [0, 75, 150, 225, 300],
        320,
        "Shares per 5-minute bar",
    )
    progress = {
        name: cumulative_percent(values, data["config"].total_qty)
        for name, values in data["executed"].items()
    }
    draw_chart_pil(
        draw,
        (70, 985, 1530, 1390),
        "Cumulative fill progress",
        data["labels"],
        progress,
        [0, 25, 50, 75, 100],
        105,
        "Percent of parent quantity",
        guide=100,
    )
    draw.text((70, 1430), "Single-session outcome", font=FONTS["section"], fill=FOREGROUND)
    draw_table_pil(
        draw,
        70,
        1475,
        [290, 220, 210, 250, 260, 230],
        metric_headers,
        metric_rows,
        header_height=62,
        row_height=76,
    )
    draw.text(
        (70, 1818),
        "Single-session research demo. Lower side-aware slippage is better; fixture volume is provider-defined tick volume.",
        font=FONTS["foot"],
        fill=MUTED,
    )
    image.save(output, format="PNG", optimize=True)


def render_svg(data: dict[str, Any], output: Path) -> None:
    measure_image = Image.new("RGB", (1, 1))
    measure_draw = ImageDraw.Draw(measure_image)
    svg = SvgBuilder()
    svg.text(70, 85, "TWAP vs Forecast VWAP vs POV", size=FONTS["title"].size, weight=700)
    svg.text(72, 126, "AAPL • BUY 5,000 shares • 5-minute bars • 2026-07-31", size=FONTS["subtitle"].size, fill=MUTED)
    decision_headers, decision_rows, metric_headers, metric_rows = figure_tables(data)
    draw_table_svg(
        svg,
        measure_draw,
        70,
        155,
        [220, 330, 250, 250, 410],
        decision_headers,
        decision_rows,
        header_height=62,
        row_height=96,
    )
    draw_chart_svg(
        svg,
        (70, 545, 1530, 950),
        "Per-bar target schedule",
        data["labels"],
        data["schedules"],
        [0, 75, 150, 225, 300],
        320,
        "Shares per 5-minute bar",
    )
    progress = {
        name: cumulative_percent(values, data["config"].total_qty)
        for name, values in data["executed"].items()
    }
    draw_chart_svg(
        svg,
        (70, 985, 1530, 1390),
        "Cumulative fill progress",
        data["labels"],
        progress,
        [0, 25, 50, 75, 100],
        105,
        "Percent of parent quantity",
        guide=100,
    )
    svg.text(70, 1459, "Single-session outcome", size=FONTS["section"].size, weight=700)
    draw_table_svg(
        svg,
        measure_draw,
        70,
        1475,
        [290, 220, 210, 250, 260, 230],
        metric_headers,
        metric_rows,
        header_height=62,
        row_height=76,
    )
    svg.text(
        70,
        1837,
        "Single-session research demo. Lower side-aware slippage is better; fixture volume is provider-defined tick volume.",
        size=FONTS["foot"].size,
        fill=MUTED,
    )
    output.write_text(svg.finish(), encoding="utf-8")


def main() -> int:
    data = load_figure_data()
    output_svg = Path(__file__).with_name("twap_vwap_pov_comparison.svg")
    output_png = Path(__file__).with_name("twap_vwap_pov_comparison.png")
    render_svg(data, output_svg)
    render_png(data, output_png)
    print(f"wrote {output_svg}")
    print(f"wrote {output_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
