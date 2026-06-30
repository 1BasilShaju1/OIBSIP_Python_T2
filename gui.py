

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QTimer, QThread, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontMetrics,
    QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
    QPolygonF, QRadialGradient,
)


sys.path.insert(0, str(Path(__file__).parent))
from core import (                                          # noqa: E402
    DayForecast, ErrorCode, HourSlot, UnitConverter, WeatherData,
    WeatherError, _sample_data, aqi_label, beaufort, deg_to_compass,
    fetch_weather, get_location_by_ip, search_cities, uv_category,
    visibility_label,
)


#  DESIGN 
class C:
    BG_DEEP    = QColor(0x04, 0x08, 0x1A)
    BG_MID     = QColor(0x06, 0x0E, 0x2A)
    BG_PANEL   = QColor(0x08, 0x12, 0x30)

    GLASS_BG   = QColor(10,  20,  60,  55)
    GLASS_BRD  = QColor(80,  160, 255, 55)
    GLASS_HOV  = QColor(30,  60,  140, 80)
    GLASS_CARD = QColor(10,  25,  70,  40)

    NEON_BLUE  = QColor(0x00, 0xB4, 0xFF)
    NEON_PURP  = QColor(0xB0, 0x00, 0xFF)
    NEON_CYAN  = QColor(0x00, 0xFF, 0xEA)
    NEON_PINK  = QColor(0xFF, 0x00, 0xC8)

    TEXT_PRI   = QColor(255, 255, 255, 255)
    TEXT_SEC   = QColor(180, 210, 255, 200)
    TEXT_MUT   = QColor(100, 150, 220, 160)
    TEXT_ACC   = QColor(0x00, 0xE4, 0xFF)

    UV_COLORS  = [
        QColor(0x00, 0xFF, 0x88), QColor(0xFF, 0xDD, 0x00),
        QColor(0xFF, 0x88, 0x00), QColor(0xFF, 0x33, 0x33),
        QColor(0xB0, 0x00, 0xFF),
    ]
    AQI_COLORS = [
        QColor(0x00, 0xFF, 0x88), QColor(0xCC, 0xDD, 0x00),
        QColor(0xFF, 0x99, 0x00), QColor(0xFF, 0x33, 0x00),
        QColor(0x99, 0x00, 0x33),
    ]


RADIUS   = 18
CARD_R   = 14
FONT_FAM = "Segoe UI" if sys.platform == "win32" else "SF Pro Display"

WEATHER_EMOJI: dict[str, str] = {
    "sun": "☀️", "partly": "⛅", "cloud": "☁️",
    "rain": "🌧️", "storm": "⛈️", "snow": "❄️",
    "fog": "🌫️", "moon": "🌙", "wind": "💨",
}

# QPainter.drawText does not do font-fallback the way QLabel rich-text does,
# so emoji drawn directly on a canvas need an explicit emoji-capable font or
# they render as empty "tofu" boxes.
_EMOJI_FONT_FAM = {
    "win32":  "Segoe UI Emoji",
    "darwin": "Apple Color Emoji",
}.get(sys.platform, "Noto Color Emoji")

# Building silhouette x-fractions for SpaceBackground
_BUILDINGS = (
    (0.02, 0.72), (0.06, 0.65), (0.10, 0.78), (0.14, 0.60),
    (0.18, 0.74), (0.22, 0.58), (0.26, 0.70), (0.30, 0.63),
    (0.34, 0.76), (0.38, 0.55), (0.42, 0.68), (0.46, 0.61),
    (0.50, 0.72), (0.54, 0.64), (0.58, 0.77), (0.62, 0.59),
    (0.66, 0.71), (0.70, 0.65), (0.74, 0.78), (0.78, 0.62),
    (0.82, 0.73), (0.86, 0.67), (0.90, 0.80), (0.94, 0.70),
    (0.98, 0.75), (1.0,  0.80),
)


#  BACKGROUND 
class SpaceBackground(QWidget):
    _TWO_PI = 2 * math.pi

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._t = 0.0
        # Pre-compute 120 stars: (x, y, radius)
        self._stars = [
            (int(i * 7) % 1400, int((i * 13 + idx * 7)) % 900, (i * 31) % 2.5)
            for idx, i in enumerate(range(120))
        ]
        self._timer = QTimer(self, interval=50, timeout=self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._t = (self._t + 0.004) % self._TWO_PI
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background gradient
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0,  QColor(4,  8,  26))
        g.setColorAt(0.4,  QColor(6,  12, 40))
        g.setColorAt(0.75, QColor(8,  18, 55))
        g.setColorAt(1.0,  QColor(4,  10, 30))
        p.fillRect(0, 0, w, h, QBrush(g))

        # Purple nebula top-left
        rg = QRadialGradient(w * 0.15, h * 0.2, h * 0.55)
        rg.setColorAt(0.0, QColor(80, 0, 160, 40))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(rg))

        # Pulsing blue glow center-right
        pulse = 0.5 + 0.5 * math.sin(self._t)
        rg2 = QRadialGradient(w * 0.85, h * 0.35, h * 0.5)
        rg2.setColorAt(0.0, QColor(0, 100, 200, int(30 + 15 * pulse)))
        rg2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(rg2))

        # Stars
        p.setPen(Qt.PenStyle.NoPen)
        for sx, sy, sr in self._stars:
            twinkle = 0.6 + 0.4 * math.sin(self._t * 2 + sx * 0.1)
            p.setBrush(QColor(200, 220, 255, int(180 * twinkle)))
            p.drawEllipse(sx % w, sy % h, int(sr) + 1, int(sr) + 1)

        # City silhouette
        path = QPainterPath()
        path.moveTo(0, h)
        path.lineTo(0, h * 0.80)
        for bx, by in _BUILDINGS:
            path.lineTo(w * bx, h * by)
        path.lineTo(w, h)
        path.closeSubpath()
        city_g = QLinearGradient(0, h * 0.55, 0, h)
        city_g.setColorAt(0.0, QColor(10, 20, 60, 200))
        city_g.setColorAt(1.0, QColor(2,  5,  20, 255))
        p.fillPath(path, QBrush(city_g))

        # Neon horizon line
        hl = h * 0.82
        hg = QLinearGradient(0, hl, w, hl)
        hg.setColorAt(0.0, QColor(0, 0, 0, 0))
        hg.setColorAt(0.3, QColor(0, 140, 255, 80))
        hg.setColorAt(0.5, QColor(160, 0, 255, 100))
        hg.setColorAt(0.7, QColor(0, 200, 255, 80))
        hg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(QPen(QBrush(hg), 1.5))
        p.drawLine(0, int(hl), w, int(hl))
        p.end()


class GlassCard(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        radius: int = CARD_R,
        alpha_bg: int = 40,
        alpha_brd: int = 55,
        glow_color: Optional[QColor] = None,
    ) -> None:
        super().__init__(parent)
        self._r         = radius
        self._alpha_bg  = alpha_bg
        self._alpha_brd = alpha_brd
        self._glow      = glow_color
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)

        p.setBrush(QColor(8, 18, 60, self._alpha_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, self._r, self._r)

        brd_color = QColor(self._glow) if self._glow else QColor(60, 120, 255)
        brd_color.setAlpha(self._alpha_brd)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(brd_color, 1.2 if self._glow else 1.0))
        p.drawRoundedRect(rect, self._r, self._r)
        p.end()


#  WORKER THREAD
class FetchWorker(QThread):
    done  = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, city: str, unit: str) -> None:
        super().__init__()
        self.city = city
        self.unit = unit

    def run(self) -> None:
        try:
            self.done.emit(fetch_weather(self.city, self.unit))
        except WeatherError as e:
            msg = f"{e.message}\n{e.hint}" if e.hint else e.message
            self.error.emit(msg)
        except Exception as e:
            self.error.emit(str(e))


class ArcGauge(QWidget):
    _SPAN       = 240
    _START_ANG  = 210 * 16  # Qt angles are in 1/16°

    def __init__(
        self,
        label: str = "",
        unit: str = "",
        max_val: float = 11,
        color: Optional[QColor] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._value  = 0.0
        self._target = 0.0
        self._anim   = 0.0
        self._label  = label
        self._unit   = unit
        self._max    = max_val
        self._color  = color or C.NEON_BLUE
        self._timer  = QTimer(self, interval=16, timeout=self._step)
        self.setFixedSize(130, 130)

    def setValue(self, v: float) -> None:
        self._target = v
        self._timer.start()

    def _step(self) -> None:
        diff        = self._target - self._anim
        self._anim += diff * 0.12
        if abs(diff) < 0.01:
            self._anim = self._target
            self._timer.stop()
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w // 2, h // 2
        r      = min(w, h) // 2 - 12

        # Track
        p.setPen(QPen(QColor(40, 80, 160, 80), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx - r, cy - r, 2 * r, 2 * r, self._START_ANG, -self._SPAN * 16)

        # Filled arc
        frac  = min(1.0, self._anim / max(self._max, 1))
        sweep = int(-frac * self._SPAN * 16)
        if sweep:
            g = QLinearGradient(cx - r, cy, cx + r, cy)
            g.setColorAt(0, self._color.lighter(160))
            g.setColorAt(1, self._color)
            p.setPen(QPen(QBrush(g), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(cx - r, cy - r, 2 * r, 2 * r, self._START_ANG, sweep)

        # Value text
        f_val = QFont(FONT_FAM, 18, QFont.Weight.Bold)
        p.setFont(f_val); p.setPen(C.TEXT_PRI)
        val_s = str(round(self._anim))
        fm    = QFontMetrics(f_val)
        p.drawText(cx - fm.horizontalAdvance(val_s) // 2, cy + fm.height() // 3, val_s)

        # Unit
        f_unit = QFont(FONT_FAM, 7); p.setFont(f_unit); p.setPen(C.TEXT_MUT)
        fm2 = QFontMetrics(f_unit)
        p.drawText(cx - fm2.horizontalAdvance(self._unit) // 2,
                   cy + fm.height() // 3 + 14, self._unit)

        # Label
        f_lbl = QFont(FONT_FAM, 8); p.setFont(f_lbl); p.setPen(C.TEXT_SEC)
        fm3 = QFontMetrics(f_lbl)
        p.drawText(cx - fm3.horizontalAdvance(self._label) // 2, h - 6, self._label)
        p.end()


#  WIND COMPASS
class WindCompass(QWidget):
    _DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._deg = 0.0; self._speed = 0.0; self._unit = "km/h"
        self.setFixedSize(130, 130)

    def setWind(self, deg: float, speed: float, unit: str) -> None:
        self._deg = deg; self._speed = speed; self._unit = unit
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w // 2, h // 2
        r      = min(w, h) // 2 - 10

        # Outer ring
        p.setPen(QPen(QColor(0, 120, 255, 60), 1.5))
        p.setBrush(QColor(0, 40, 120, 30))
        p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # Cardinal / intercardinal ticks and labels
        f_dir = QFont(FONT_FAM, 7, QFont.Weight.Bold)
        for i, d in enumerate(self._DIRS):
            angle = math.radians(i * 45)
            major = (i % 2 == 0)
            tl    = 9 if major else 5
            sin_a, cos_a = math.sin(angle), math.cos(angle)
            x1 = cx + (r - 1)      * sin_a;  y1 = cy - (r - 1)      * cos_a
            x2 = cx + (r - 1 - tl) * sin_a;  y2 = cy - (r - 1 - tl) * cos_a
            p.setPen(QPen(QColor(0, 200, 255, 150 if major else 70), 1))
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            if major:
                p.setFont(f_dir)
                p.setPen(QColor(0, 255, 200, 255) if d == "N" else QColor(140, 180, 255, 200))
                lx = cx + (r - 21) * sin_a; ly = cy - (r - 21) * cos_a
                fm = QFontMetrics(f_dir)
                p.drawText(int(lx - fm.horizontalAdvance(d) // 2),
                           int(ly + fm.height() // 3), d)

        # Direction arrow
        rad    = math.radians(self._deg)
        sin_r, cos_r = math.sin(rad), math.cos(rad)
        tip  = (cx + (r - 14) * sin_r,  cy - (r - 14) * cos_r)
        tail = (cx - 16 * sin_r,         cy + 16 * cos_r)
        sa   = rad + math.pi / 2;  sl = 6
        sx1  = cx + 4 * sin_r + sl * math.sin(sa); sy1 = cy - 4 * cos_r - sl * math.cos(sa)
        sx2  = cx + 4 * sin_r - sl * math.sin(sa); sy2 = cy - 4 * cos_r + sl * math.cos(sa)
        path = QPainterPath()
        path.moveTo(*tip); path.lineTo(sx1, sy1)
        path.lineTo(*tail); path.lineTo(sx2, sy2)
        path.closeSubpath()
        ag = QLinearGradient(tail[0], tail[1], tip[0], tip[1])
        ag.setColorAt(0, QColor(0, 80, 200, 180)); ag.setColorAt(1, QColor(0, 200, 255, 255))
        p.setBrush(QBrush(ag)); p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, QBrush(ag))

        # Speed label
        f_spd = QFont(FONT_FAM, 11, QFont.Weight.Bold)
        p.setFont(f_spd); p.setPen(C.TEXT_PRI)
        spd_s = str(round(self._speed))
        fm    = QFontMetrics(f_spd)
        p.drawText(cx - fm.horizontalAdvance(spd_s) // 2, cy + fm.height() // 3, spd_s)
        f_u = QFont(FONT_FAM, 7); p.setFont(f_u); p.setPen(C.TEXT_MUT)
        fm2 = QFontMetrics(f_u)
        p.drawText(cx - fm2.horizontalAdvance(self._unit) // 2,
                   cy + fm.height() // 3 + 13, self._unit)
        p.end()


#  SUN 
class SunArcWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._frac = 0.5; self._rise = "06:19"; self._set = "18:42"
        self.setFixedHeight(80)

    def setData(self, rise: str, sset: str, now_hm: Optional[str] = None) -> None:
        """
        rise / sset: city-local "HH:MM" strings.
        now_hm: city-local current time as "HH:MM". If omitted, falls back to
        the machine's local clock (only correct if viewing weather for your
        own timezone).
        """
        self._rise = rise; self._set = sset
        try:
            def t2m(s: str) -> int:
                h, m = map(int, s.split(":"))
                return h * 60 + m

            if now_hm:
                now_m = t2m(now_hm)
            else:
                now_m = datetime.now().hour * 60 + datetime.now().minute

            span = t2m(sset) - t2m(rise)
            self._frac = max(0.0, min(1.0, (now_m - t2m(rise)) / max(span, 1)))
        except Exception:
            self._frac = 0.5
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w // 2, h - 12
        rx, ry = w // 2 - 18, h - 14

        # Arc track
        path = QPainterPath()
        path.moveTo(cx - rx, cy)
        path.arcTo(cx - rx, cy - ry, 2 * rx, 2 * ry, 0, 180)
        p.setPen(QPen(QColor(0, 120, 220, 60), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Sun
        angle = math.pi - self._frac * math.pi
        sx    = cx + rx * math.cos(angle)
        sy    = cy - ry * math.sin(angle)
        rg    = QRadialGradient(sx, sy, 20)
        rg.setColorAt(0.0, QColor(255, 220, 80,  230))
        rg.setColorAt(0.5, QColor(255, 140, 0,   80))
        rg.setColorAt(1.0, QColor(0,   0,   0,   0))
        p.setBrush(QBrush(rg)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(sx - 20), int(sy - 20), 40, 40)
        p.setBrush(QColor(255, 220, 100, 230))
        p.drawEllipse(int(sx - 5), int(sy - 5), 10, 10)

        # Horizon
        p.setPen(QPen(QColor(0, 100, 200, 70), 1))
        p.drawLine(cx - rx - 3, cy, cx + rx + 3, cy)

        # Labels
        f = QFont(FONT_FAM, 7); p.setFont(f); p.setPen(C.TEXT_SEC)
        fm = QFontMetrics(f)
        p.drawText(cx - rx - fm.horizontalAdvance(self._rise) - 1, cy + 12, self._rise)
        p.drawText(cx + rx + 2, cy + 12, self._set)
        p.end()


#  HOURLY CHART
class HourlyChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._slots: List[HourSlot] = []
        self.setFixedHeight(150)

    def setSlots(self, slots: List[HourSlot]) -> None:
        self._slots = slots[:12]
        self.update()

    def paintEvent(self, _) -> None:
        if not self._slots:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h  = self.width(), self.height()
        n     = len(self._slots)
        col_w = w / n
        temps = [s.temp for s in self._slots]
        lo, hi = min(temps), max(temps)
        rng    = max(hi - lo, 1)

        bar_top   = h * 0.52
        bar_max_h = h * 0.28
        label_h   = h * 0.16

        # Bars — remember each column's own top-y so the emoji can sit
        # directly above *that* bar instead of a fixed baseline.
        bar_tops: List[float] = []
        for i, slot in enumerate(self._slots):
            x    = i * col_w
            frac = (slot.temp - lo) / rng
            bh   = bar_max_h * (0.25 + 0.75 * frac)
            bx   = x + col_w * 0.2
            bw   = col_w * 0.6
            top_y = bar_top + bar_max_h - bh
            bar_tops.append(top_y)
            bg   = QLinearGradient(bx, bar_top, bx, bar_top + bar_max_h)
            bg.setColorAt(0, QColor(0, 160, 255, 220))
            bg.setColorAt(1, QColor(100, 0, 255, 60))
            p.setBrush(QBrush(bg)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(int(bx), int(top_y), int(bw), int(bh), 3, 3)

        # Sparkline points
        pts = [
            QPointF(
                (i + 0.5) * col_w,
                bar_top - 5 - ((s.temp - lo) / rng) * (bar_top - label_h - 10),
            )
            for i, s in enumerate(self._slots)
        ]

        if len(pts) > 1:
            path = QPainterPath()
            path.moveTo(pts[0])
            for i in range(1, len(pts)):
                cx_ = (pts[i - 1].x() + pts[i].x()) / 2
                path.cubicTo(cx_, pts[i - 1].y(), cx_, pts[i].y(), pts[i].x(), pts[i].y())

            # Glow pass then main line
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 200, 255, 60), 6,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(0, 200, 255, 220), 2,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

            # Dots
            p.setBrush(QColor(0, 220, 255, 240))
            p.setPen(QPen(QColor(255, 255, 255, 180), 1))
            for pt in pts:
                p.drawEllipse(pt, 3.5, 3.5)

        # Text labels
        f_sm = QFont(FONT_FAM, 7)
        f_em = QFont(_EMOJI_FONT_FAM, 11)
        f_tmp = QFont(FONT_FAM, 8, QFont.Weight.Bold)
        for i, slot in enumerate(self._slots):
            cx_ = int((i + 0.5) * col_w)
            if slot.period:
                p.setFont(f_sm); p.setPen(QColor(0, 180, 255, 140))
                fm = QFontMetrics(f_sm)
                p.drawText(cx_ - fm.horizontalAdvance(slot.period) // 2, 11, slot.period)

            p.setFont(f_em)
            # Sit just above this column's own bar peak, but never creep up
            # into the sparkline's drawing zone for the tallest bars.
            emoji_y = max(int(bar_tops[i] - 6), int(label_h + 14))
            p.drawText(cx_ - 9, emoji_y, WEATHER_EMOJI.get(slot.kind, "🌤"))

            p.setFont(f_sm); p.setPen(C.TEXT_MUT)
            fm = QFontMetrics(f_sm)
            p.drawText(cx_ - fm.horizontalAdvance(slot.time) // 2, int(h - 22), slot.time)

            p.setFont(f_tmp); p.setPen(C.TEXT_PRI)
            tmp_s = f"{round(slot.temp)}°"
            fm2 = QFontMetrics(f_tmp)
            p.drawText(cx_ - fm2.horizontalAdvance(tmp_s) // 2, int(h - 8), tmp_s)
        p.end()


#  DAILY FORECAST 
class DailyForecastCard(GlassCard):
    def __init__(self, day: DayForecast, unit: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, radius=12, alpha_bg=35, alpha_brd=50, glow_color=C.NEON_BLUE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for text, style in (
            (day.day,  "color:rgba(0,200,255,220);font-size:10px;font-weight:700;letter-spacing:1px;"),
            (day.date, "color:rgba(140,180,255,160);font-size:8px;"),
        ):
            lbl = QLabel(text)
            lbl.setStyleSheet(style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl)

        emoji = QLabel(WEATHER_EMOJI.get(day.kind, "🌤"))
        emoji.setStyleSheet("font-size:22px;")
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        desc = QLabel(day.desc)
        desc.setStyleSheet("color:rgba(180,210,255,180);font-size:8px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        lay.addWidget(desc)

        hi_lbl = QLabel(f"↑{round(day.high)}{unit}")
        hi_lbl.setStyleSheet("color:rgba(255,200,80,230);font-size:11px;font-weight:700;")
        hi_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hi_lbl)

        lo_lbl = QLabel(f"↓{round(day.low)}{unit}")
        lo_lbl.setStyleSheet("color:rgba(100,180,255,200);font-size:9px;font-weight:600;")
        lo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lo_lbl)

        self.setFixedWidth(108)


#  STATS
class StatCard(GlassCard):
    def __init__(self, icon: str, label: str, value: str = "—",
                 sub: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, radius=12, alpha_bg=35, alpha_brd=45, glow_color=C.NEON_BLUE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)

        top = QHBoxLayout()
        ico = QLabel(icon); ico.setStyleSheet("font-size:13px;")
        lbl = QLabel(label.upper())
        lbl.setStyleSheet("color:rgba(0,180,255,180);font-size:8px;letter-spacing:1.5px;")
        top.addWidget(ico); top.addWidget(lbl); top.addStretch()
        lay.addLayout(top)

        self._val = QLabel(value)
        self._val.setStyleSheet("color:white;font-size:17px;font-weight:700;")
        lay.addWidget(self._val)

        self._sub = QLabel(sub)
        self._sub.setStyleSheet("color:rgba(100,160,255,180);font-size:8px;")
        lay.addWidget(self._sub)

    def update_value(self, value: str, sub: str = "") -> None:
        self._val.setText(value)
        self._sub.setText(sub)


#  SEARCH BAR
class SearchBar(GlassCard):
    search_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, radius=22, alpha_bg=45, alpha_brd=70, glow_color=C.NEON_BLUE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Search city…")
        self._edit.setStyleSheet(
            "QLineEdit{background:transparent;border:none;color:white;font-size:13px;font-weight:500;}"
        )
        self._edit.returnPressed.connect(self._on_search)
        lay.addWidget(self._edit)

        self._btn = QPushButton("Search")
        self._btn.setFixedSize(76, 32)
        self._btn.setStyleSheet("""
            QPushButton{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 rgba(0,140,255,200),stop:1 rgba(100,0,255,200));
                border-radius:16px;color:white;font-weight:700;font-size:11px;border:none;
            }
            QPushButton:hover{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 rgba(0,180,255,230),stop:1 rgba(140,0,255,230));
            }
        """)
        self._btn.clicked.connect(self._on_search)
        lay.addWidget(self._btn)
        self.setFixedHeight(44)

    def _on_search(self) -> None:
        t = self._edit.text().strip()
        if t:
            self.search_requested.emit(t)

    def set_city(self, city: str) -> None:
        self._edit.setText(city)


#  UNIT TOGGLE
_ACTIVE_BTN_SS = """QPushButton{
    background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 rgba(0,140,255,200),stop:1 rgba(100,0,255,200));
    border-radius:14px;color:white;font-weight:700;font-size:12px;border:none;}"""

_IDLE_BTN_SS = """QPushButton{
    background:transparent;border-radius:14px;
    color:rgba(140,180,255,180);font-weight:600;font-size:12px;border:none;}
    QPushButton:hover{background:rgba(0,80,160,60);}"""


class UnitToggle(GlassCard):
    toggled = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, radius=18, alpha_bg=40, alpha_brd=60, glow_color=C.NEON_BLUE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3); lay.setSpacing(2)
        self._unit  = "metric"
        self._c_btn = self._make_btn("°C", active=True)
        self._f_btn = self._make_btn("°F", active=False)
        lay.addWidget(self._c_btn); lay.addWidget(self._f_btn)
        self.setFixedSize(96, 36)
        self._c_btn.clicked.connect(lambda: self._select("metric"))
        self._f_btn.clicked.connect(lambda: self._select("imperial"))

    def _make_btn(self, text: str, active: bool) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(42, 28)
        b.setStyleSheet(_ACTIVE_BTN_SS if active else _IDLE_BTN_SS)
        return b

    def _select(self, unit: str) -> None:
        self._unit = unit
        self._c_btn.setStyleSheet(_ACTIVE_BTN_SS if unit == "metric"   else _IDLE_BTN_SS)
        self._f_btn.setStyleSheet(_ACTIVE_BTN_SS if unit == "imperial" else _IDLE_BTN_SS)
        self.toggled.emit(unit)

    def current(self) -> str:
        return self._unit


#  SPINNER
class Spinner(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self, interval=30, timeout=self._tick)
        self.setFixedSize(48, 48)
        self.hide()

    def start(self) -> None: self.show(); self._timer.start()
    def stop(self)  -> None: self.hide(); self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        r = 18
        for i in range(12):
            a = math.radians(self._angle + i * 30)
            p.setPen(QPen(QColor(0, 180, 255, int(255 * i / 12)), 2.5,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(
                int(cx + (r - 6) * math.cos(a)), int(cy - (r - 6) * math.sin(a)),
                int(cx + r * math.cos(a)),        int(cy - r * math.sin(a)),
            )
        p.end()


#  STATUS BAR
_SS_OK  = "color:rgba(100,160,255,140);font-size:9px;background:transparent;"
_SS_ERR = "color:rgba(255,80,120,200);font-size:9px;background:transparent;"


class StatusBar(QLabel):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_SS_OK + "padding:1px 8px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_ok(self, msg: str) -> None:
        self.setStyleSheet(_SS_OK); self.setText(msg)

    def set_error(self, msg: str) -> None:
        self.setStyleSheet(_SS_ERR); self.setText("⚠  " + msg)


#  DASHBOARD
class Dashboard(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._data: Optional[WeatherData] = None
        self._unit = "metric"
        self._build_ui()

    # ── Layout builders
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(10)

        row1 = QHBoxLayout(); row1.setSpacing(10)
        self._cur_card = self._build_current_card()
        row1.addWidget(self._cur_card, 32)
        self._hi_panel = self._build_highlights_panel()
        row1.addWidget(self._hi_panel, 68)
        root.addLayout(row1, 46)

        row2 = QHBoxLayout(); row2.setSpacing(10)
        self._hourly_card = self._build_hourly_card()
        row2.addWidget(self._hourly_card, 55)
        self._daily_card = self._build_daily_card()
        row2.addWidget(self._daily_card, 45)
        root.addLayout(row2, 30)

    def _build_current_card(self) -> GlassCard:
        card = GlassCard(radius=CARD_R, alpha_bg=45, alpha_brd=65, glow_color=C.NEON_BLUE)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18); lay.setSpacing(5)

        self._city_lbl = QLabel("— City —")
        self._city_lbl.setStyleSheet(
            "color:white;font-size:24px;font-weight:800;letter-spacing:0.5px;")
        lay.addWidget(self._city_lbl)

        self._country_lbl = QLabel("Country")
        self._country_lbl.setStyleSheet("color:rgba(0,200,255,180);font-size:11px;")
        lay.addWidget(self._country_lbl)

        mid = QHBoxLayout()
        self._emoji_lbl = QLabel("⛅")
        self._emoji_lbl.setStyleSheet("font-size:68px;")
        mid.addWidget(self._emoji_lbl); mid.addStretch()

        temp_col = QVBoxLayout()
        self._temp_lbl = QLabel("—°")
        self._temp_lbl.setStyleSheet("color:white;font-size:58px;font-weight:700;")
        temp_col.addWidget(self._temp_lbl)
        self._fl_lbl = QLabel("Feels like —°")
        self._fl_lbl.setStyleSheet("color:rgba(0,200,255,200);font-size:11px;")
        temp_col.addWidget(self._fl_lbl)
        mid.addLayout(temp_col)
        lay.addLayout(mid)

        self._desc_lbl = QLabel("Partly Cloudy")
        self._desc_lbl.setStyleSheet(
            "color:rgba(200,220,255,220);font-size:15px;font-weight:500;")
        lay.addWidget(self._desc_lbl)

        mm = QHBoxLayout()
        self._min_lbl = QLabel("↓ —°")
        self._min_lbl.setStyleSheet(
            "color:rgba(100,180,255,220);font-size:12px;font-weight:600;")
        self._max_lbl = QLabel("↑ —°")
        self._max_lbl.setStyleSheet(
            "color:rgba(255,200,80,220);font-size:12px;font-weight:600;")
        mm.addWidget(self._min_lbl); mm.addStretch(); mm.addWidget(self._max_lbl)
        lay.addLayout(mm)

        lay.addStretch()
        self._ts_lbl = QLabel("")
        self._ts_lbl.setStyleSheet("color:rgba(80,140,255,130);font-size:9px;")
        lay.addWidget(self._ts_lbl)
        return card

    @staticmethod
    def _hdr_lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet("color:rgba(100,160,255,180);font-size:8px;letter-spacing:1px;")
        return l

    def _build_highlights_panel(self) -> GlassCard:
        card = GlassCard(radius=CARD_R, alpha_bg=35, alpha_brd=50)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(8)

        title = QLabel("TODAY'S HIGHLIGHTS")
        title.setStyleSheet(
            "color:rgba(0,200,255,200);font-size:10px;font-weight:700;letter-spacing:3px;")
        lay.addWidget(title)

        row1 = QHBoxLayout(); row1.setSpacing(8)
        row2 = QHBoxLayout(); row2.setSpacing(8)

        # Wind
        wind_card = GlassCard(radius=12, alpha_bg=40, alpha_brd=50, glow_color=C.NEON_BLUE)
        wl = QVBoxLayout(wind_card); wl.setContentsMargins(10, 8, 10, 8); wl.setSpacing(2)
        wl.addWidget(self._hdr_lbl("💨  WIND STATUS"))
        self._compass = WindCompass()
        wl.addWidget(self._compass, 0, Qt.AlignmentFlag.AlignHCenter)
        self._wind_dir_lbl = QLabel("—")
        self._wind_dir_lbl.setStyleSheet("color:rgba(0,200,255,200);font-size:10px;")
        self._wind_dir_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wl.addWidget(self._wind_dir_lbl)
        row1.addWidget(wind_card)

        # UV
        uv_card = GlassCard(radius=12, alpha_bg=40, alpha_brd=50, glow_color=C.NEON_PURP)
        ul = QVBoxLayout(uv_card); ul.setContentsMargins(10, 8, 10, 8); ul.setSpacing(2)
        ul.addWidget(self._hdr_lbl("☀️  UV INDEX"))
        self._uv_gauge = ArcGauge("UV Index", "", 11, C.NEON_PURP)
        ul.addWidget(self._uv_gauge, 0, Qt.AlignmentFlag.AlignHCenter)
        self._uv_label = QLabel("—")
        self._uv_label.setStyleSheet("color:rgba(180,100,255,200);font-size:10px;")
        self._uv_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ul.addWidget(self._uv_label)
        row1.addWidget(uv_card)

        # Sunrise/Sunset
        sun_card = GlassCard(radius=12, alpha_bg=40, alpha_brd=50, glow_color=C.NEON_CYAN)
        sl = QVBoxLayout(sun_card); sl.setContentsMargins(10, 8, 10, 8); sl.setSpacing(2)
        sl.addWidget(self._hdr_lbl("🌅  SUNRISE & SUNSET"))
        self._sun_arc = SunArcWidget()
        sl.addWidget(self._sun_arc)
        sun_row = QHBoxLayout()
        self._rise_lbl = QLabel("↑ —")
        self._set_lbl  = QLabel("↓ —")
        for lbl in (self._rise_lbl, self._set_lbl):
            lbl.setStyleSheet("color:rgba(255,210,80,230);font-size:11px;font-weight:600;")
        self._day_lbl = QLabel("Day: —")
        self._day_lbl.setStyleSheet("color:rgba(140,180,255,160);font-size:9px;")
        sun_row.addWidget(self._rise_lbl); sun_row.addStretch()
        sun_row.addWidget(self._set_lbl)
        sl.addLayout(sun_row); sl.addWidget(self._day_lbl)
        row1.addWidget(sun_card, 1)

        # Humidity
        hum_card = GlassCard(radius=12, alpha_bg=40, alpha_brd=50, glow_color=C.NEON_CYAN)
        hl = QVBoxLayout(hum_card); hl.setContentsMargins(10, 8, 10, 8); hl.setSpacing(2)
        hl.addWidget(self._hdr_lbl("💧  HUMIDITY"))
        self._hum_gauge = ArcGauge("Humidity", "%", 100, C.NEON_CYAN)
        hl.addWidget(self._hum_gauge, 0, Qt.AlignmentFlag.AlignHCenter)
        self._dew_lbl = QLabel("Dew: —")
        self._dew_lbl.setStyleSheet("color:rgba(0,220,255,180);font-size:9px;")
        self._dew_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(self._dew_lbl)
        row2.addWidget(hum_card)

        # Stat cards
        self._press_card  = StatCard("🧭", "Pressure",      "— hPa", "Normal")
        self._vis_card    = StatCard("👁️", "Visibility",    "— km",  "—")
        self._precip_card = StatCard("🌧️", "Precipitation", "—%",    "Chance of rain")
        for sc in (self._press_card, self._vis_card, self._precip_card):
            row2.addWidget(sc)

        lay.addLayout(row1); lay.addLayout(row2)
        return card

    def _build_hourly_card(self) -> GlassCard:
        card = GlassCard(radius=CARD_R, alpha_bg=38, alpha_brd=50)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 8); lay.setSpacing(5)
        hdr = QLabel("HOURLY FORECAST")
        hdr.setStyleSheet(
            "color:rgba(0,200,255,200);font-size:10px;font-weight:700;letter-spacing:3px;")
        lay.addWidget(hdr)
        self._hourly_chart = HourlyChart()
        lay.addWidget(self._hourly_chart)
        return card

    def _build_daily_card(self) -> GlassCard:
        card = GlassCard(radius=CARD_R, alpha_bg=38, alpha_brd=50)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(8)
        hdr = QLabel("7-DAY FORECAST")
        hdr.setStyleSheet(
            "color:rgba(0,200,255,200);font-size:10px;font-weight:700;letter-spacing:3px;")
        lay.addWidget(hdr)

        self._daily_scroll = QScrollArea()
        self._daily_scroll.setWidgetResizable(True)
        self._daily_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._daily_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._daily_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._daily_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;} QScrollBar:horizontal{height:0px;}")

        self._daily_inner = QWidget()
        self._daily_inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._daily_row = QHBoxLayout(self._daily_inner)
        self._daily_row.setContentsMargins(0, 0, 0, 0)
        self._daily_row.setSpacing(8)
        self._daily_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._daily_scroll.setWidget(self._daily_inner)
        lay.addWidget(self._daily_scroll)
        return card

    def _rebuild_daily(self, daily: List[DayForecast], unit: str) -> None:
        # Clear existing widgets
        while self._daily_row.count():
            item = self._daily_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for day in daily[:7]:
            self._daily_row.addWidget(DailyForecastCard(day, unit))
        self._daily_row.addStretch()

    # ── Data binding
    def populate(self, data: WeatherData, unit: str = "metric") -> None:
        self._data = data
        self._unit = unit
        u  = data.unit_symbol
        wu = data.wind_unit

        self._city_lbl.setText(data.city)
        self._country_lbl.setText(f"{data.country}  ·  {data.lat:.2f}°N, {data.lon:.2f}°E")
        self._emoji_lbl.setText(WEATHER_EMOJI.get(data.kind, "🌤"))
        self._temp_lbl.setText(f"{round(data.temp)}{u}")
        self._fl_lbl.setText(f"Feels like {round(data.feels_like)}{u}")
        self._desc_lbl.setText(data.description.capitalize())
        self._min_lbl.setText(f"↓ {round(data.temp_min)}{u}")
        self._max_lbl.setText(f"↑ {round(data.temp_max)}{u}")
        self._ts_lbl.setText(data.timestamp)

        self._compass.setWind(data.wind_deg, data.wind_speed, wu)
        self._wind_dir_lbl.setText(f"{deg_to_compass(data.wind_deg)}  ·  {beaufort(data.wind_speed)}")

        self._uv_gauge.setValue(data.uv_index)
        self._uv_label.setText(uv_category(data.uv_index))

        self._sun_arc.setData(data.sunrise, data.sunset, data.local_time_hm)
        self._rise_lbl.setText(f"↑  {data.sunrise}")
        self._set_lbl.setText(f"↓  {data.sunset}")
        self._day_lbl.setText(f"Day length: {data.day_length}")

        self._hum_gauge.setValue(data.humidity)
        self._dew_lbl.setText(f"Dew point: {round(data.dew_point)}{u}")

        self._press_card.update_value(
            f"{round(data.pressure)} hPa",
            "Low" if data.pressure < 1000 else "Normal" if data.pressure < 1020 else "High",
        )
        self._vis_card.update_value(f"{data.visibility} km", visibility_label(data.visibility))
        self._precip_card.update_value(f"{round(data.precipitation)}%", "Chance of rain")

        self._hourly_chart.setSlots(data.hourly)
        self._rebuild_daily(data.daily, u)


#  MAIN WINDOW
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Weather Dashboard")
        self.setMinimumSize(1100, 740)
        self.resize(1400, 880)

        self._unit: str = "metric"
        self._current_data: Optional[WeatherData] = None
        self._worker: Optional[FetchWorker] = None

        self._bg = SpaceBackground(self)
        self._bg.setGeometry(self.rect())

        self._root = QWidget(self)
        self._root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._root.setGeometry(self.rect())

        self._build_layout()
        self._load_demo()

        self._clock_timer = QTimer(self, interval=1000, timeout=self._update_clock)
        self._clock_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg.setGeometry(self.rect())
        self._root.setGeometry(self.rect())
        self._position_spinner()

    def _build_layout(self) -> None:
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        topbar.setFixedHeight(64)
        tbl = QHBoxLayout(topbar)
        tbl.setContentsMargins(22, 10, 22, 10); tbl.setSpacing(12)

        logo = QLabel("WEATHER")
        logo.setStyleSheet("color:white;font-size:20px;font-weight:900;letter-spacing:6px;")
        tbl.addWidget(logo)

        sep = QLabel("·")
        sep.setStyleSheet("color:rgba(0,180,255,120);font-size:18px;")
        tbl.addWidget(sep)
        tbl.addStretch()

        self._search = SearchBar()
        self._search.setFixedWidth(380)
        self._search.search_requested.connect(self._on_search)
        tbl.addWidget(self._search)
        tbl.addStretch()

        self._unit_toggle = UnitToggle()
        self._unit_toggle.toggled.connect(self._on_unit_toggle)
        tbl.addWidget(self._unit_toggle)

        self._refresh_btn = QPushButton("↻  Refresh")
        self._refresh_btn.setFixedSize(96, 36)
        self._refresh_btn.setStyleSheet("""
            QPushButton{
                background:rgba(0,80,180,80);border-radius:18px;
                color:rgba(100,200,255,220);font-size:11px;font-weight:600;
                border:1px solid rgba(0,140,255,80);
            }
            QPushButton:hover{background:rgba(0,100,220,120);color:white;}
        """)
        self._refresh_btn.clicked.connect(self._on_refresh)
        tbl.addWidget(self._refresh_btn)

        self._clock_lbl = QLabel("")
        self._clock_lbl.setStyleSheet(
            "color:rgba(100,180,255,200);font-size:12px;font-weight:500;")
        tbl.addWidget(self._clock_lbl)
        self._update_clock()
        outer.addWidget(topbar)

        self._dashboard = Dashboard()
        outer.addWidget(self._dashboard, 1)

        self._status = StatusBar()
        self._status.setFixedHeight(18)
        outer.addWidget(self._status)

        self._spinner = Spinner()
        self._spinner.setParent(self._root)
        self._spinner.raise_()

    def _position_spinner(self) -> None:
        self._spinner.move(self.width() // 2 - 24, self.height() // 2 - 24)

    def _load_demo(self) -> None:
        data = _sample_data(self._unit)
        self._current_data = data
        self._dashboard.populate(data, self._unit)
        self._status.set_ok("Demo data  ·  Set OWM_API_KEY for live weather")
        self._search.set_city(data.city)

    def _fetch(self, city: str) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._position_spinner(); self._spinner.start()
        self._status.set_ok("Fetching weather…")
        self._refresh_btn.setEnabled(False)
        self._worker = FetchWorker(city, self._unit)
        self._worker.done.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(object)
    def _on_data(self, data: WeatherData) -> None:
        self._spinner.stop(); self._refresh_btn.setEnabled(True)
        self._current_data = data
        self._dashboard.populate(data, self._unit)
        self._search.set_city(data.city)
        status = f"Updated: {data.timestamp}"
        if data.status:
            status += f"  ·  {data.status}"
        self._status.set_ok(status)

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        self._spinner.stop(); self._refresh_btn.setEnabled(True)
        self._status.set_error(msg)

    def _on_search(self, query: str) -> None:
        if query == "__locate__":
            self._status.set_ok("Detecting location…")
            loc = get_location_by_ip()
            if loc:
                self._fetch(loc.name)
            else:
                self._status.set_error("Could not detect location.")
            return
        self._fetch(query)

    def _on_unit_toggle(self, unit: str) -> None:
        self._unit = unit
        if self._current_data:
            try:
                converted = UnitConverter.convert(self._current_data, unit)
                self._dashboard.populate(converted, unit)
            except Exception as e:
                self._status.set_error(f"Unit conversion failed: {e}")

    def _on_refresh(self) -> None:
        if self._current_data:
            self._fetch(self._current_data.city)
        else:
            self._load_demo()

    def _update_clock(self) -> None:
        self._clock_lbl.setText(datetime.now().strftime("%H:%M:%S  ·  %d %b %Y"))


#  ENTRY POINT
def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Weather")
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAM, 10))

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,     QColor(4, 8, 26))
    pal.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    pal.setColor(QPalette.ColorRole.Base,       QColor(8, 18, 55))
    pal.setColor(QPalette.ColorRole.Text,       Qt.GlobalColor.white)
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()