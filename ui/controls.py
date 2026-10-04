"""The two iOS controls a stylesheet cannot draw.

Everything else in this window is a standard Qt widget wearing the QSS in
ui/theme.py. These two are not, for the same reason in both cases: QSS can paint
a widget's box, but it cannot move a piece of that box around inside it. A
segmented control needs a thumb that sits behind one segment of several, and a
switch needs a knob that travels from one end of a track to the other. Both are
positions, not styles, so both need a paintEvent.

They are kept together here rather than beside the panels that use them because
neither is specific to a panel: the mode toggle and the schema-source picker are
the same control with different labels.
"""

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QWidget

from .theme import (
    ACCENT,
    BORDER,
    CARD_BG,
    FILL,
    TEXT_MUTED,
    TEXT_PRIMARY,
)

# --- segmented control -------------------------------------------------------
# iOS draws the track a hair larger than the thumb and insets the thumb by a
# couple of points on every side, which is what gives the selected segment its
# lifted look. The radii follow from that: the thumb's corner has to sit inside
# the track's, or the two curves fight at the corners.
_SEG_HEIGHT = 32
_SEG_PAD = 2
_SEG_RADIUS = 9
_SEG_THUMB_RADIUS = 7
_SEG_H_PADDING = 18  # horizontal breathing room per label


class SegmentedControl(QWidget):
    """A row of mutually exclusive labels with a thumb behind the chosen one.

    Deliberately not a QButtonGroup of styled QRadioButtons, which is what this
    replaced: separate buttons cannot share a track, so the thumb has to be the
    button's own background and the gaps between the buttons show through the
    control. One widget painting the whole row has no gaps to leak.
    """

    currentChanged = Signal(int)

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self._segments = list(segments)
        self._current = 0
        self._hovered = -1
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(_SEG_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # -------------------------------------------------------------------- api

    def currentIndex(self) -> int:
        return self._current

    def setCurrentIndex(self, index: int) -> None:
        """Select a segment, emitting currentChanged even when set in code.

        Emitting on a programmatic set is the opposite of QButtonGroup's
        idClicked, which this replaced, and is the behaviour the window wants:
        every caller that sets the mode also wants the mode applied, and the one
        that used to do both by hand can now do neither.
        """
        if not 0 <= index < len(self._segments) or index == self._current:
            return
        self._current = index
        self.update()
        self.currentChanged.emit(index)

    def segmentCount(self) -> int:
        return len(self._segments)

    # ------------------------------------------------------------------ input

    def _segment_at(self, x: float) -> int:
        if not self._segments:
            return -1
        width = self.width() / len(self._segments)
        return max(0, min(len(self._segments) - 1, int(x // width)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setCurrentIndex(self._segment_at(event.position().x()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        hovered = self._segment_at(event.position().x()) if self.isEnabled() else -1
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        # Arrow keys move the selection, matching how a segmented control
        # behaves everywhere else it exists.
        if event.key() == Qt.Key_Left:
            self.setCurrentIndex(self._current - 1)
        elif event.key() == Qt.Key_Right:
            self.setCurrentIndex(self._current + 1)
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------------- layout

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        # Every segment is the width of the widest label, so the thumb does not
        # change size as the selection moves.
        widest = max((metrics.horizontalAdvance(s) for s in self._segments), default=0)
        return QSize((widest + 2 * _SEG_H_PADDING) * max(len(self._segments), 1), _SEG_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ------------------------------------------------------------------ paint

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()

        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(FILL))
        painter.drawRoundedRect(rect, _SEG_RADIUS, _SEG_RADIUS)

        if not self._segments:
            return

        width = rect.width() / len(self._segments)

        # Hairlines between unselected neighbours, the way iOS separates
        # segments that have no thumb between them. Skipped either side of the
        # selection, where the thumb is the separator.
        painter.setBrush(QColor(BORDER))
        for i in range(1, len(self._segments)):
            if i == self._current or i - 1 == self._current:
                continue
            x = rect.left() + width * i
            painter.drawRect(QRectF(x - 0.5, rect.top() + 7, 1.0, rect.height() - 14))

        thumb = QRectF(
            rect.left() + width * self._current + _SEG_PAD,
            rect.top() + _SEG_PAD,
            width - 2 * _SEG_PAD,
            rect.height() - 2 * _SEG_PAD,
        )
        # Two passes stand in for iOS's drop shadow, which QPainter has no cheap
        # equivalent for: a barely-there dark halo one pixel below the thumb,
        # then the thumb itself over it.
        shadow = QPainterPath()
        shadow.addRoundedRect(thumb.translated(0, 1), _SEG_THUMB_RADIUS, _SEG_THUMB_RADIUS)
        painter.fillPath(shadow, QColor(0, 0, 0, 28 if enabled else 12))

        painter.setBrush(QColor(CARD_BG))
        painter.drawRoundedRect(thumb, _SEG_THUMB_RADIUS, _SEG_THUMB_RADIUS)

        for i, label in enumerate(self._segments):
            selected = i == self._current
            font = QFont(self.font())
            font.setWeight(QFont.DemiBold if selected else QFont.Normal)
            painter.setFont(font)
            if not enabled:
                colour = QColor(TEXT_MUTED)
                colour.setAlpha(110)
            elif selected:
                colour = QColor(TEXT_PRIMARY)
            elif i == self._hovered:
                colour = QColor(TEXT_PRIMARY)
            else:
                colour = QColor(TEXT_MUTED)
            painter.setPen(colour)
            painter.drawText(
                QRectF(rect.left() + width * i, rect.top(), width, rect.height()),
                Qt.AlignCenter,
                label,
            )


# --- switch ------------------------------------------------------------------
_SW_WIDTH = 40
_SW_HEIGHT = 24
_SW_KNOB_INSET = 2
_SW_GAP = 8  # between the label and the track


class ToggleSwitch(QCheckBox):
    """An iOS switch that keeps QCheckBox's API.

    Subclassing QCheckBox rather than writing a fresh widget is the whole point:
    the window already calls isChecked/setEnabled/setVisible/setToolTip on this
    thing and connects to toggled, and none of that had to change to make it
    look like a switch. Only the painting is ours.

    The label is drawn here too, to its left, because that is the side iOS puts
    it on -- QCheckBox would otherwise put its own text after the indicator.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._offset = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # Duration and curve are iOS's: fast enough not to delay the click,
        # eased so the knob settles rather than stopping dead.
        self._animation = QPropertyAnimation(self, b"knobOffset", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self._offset = 1.0 if self.isChecked() else 0.0

    # 0.0 = off end of the track, 1.0 = on end. Animated rather than jumped, so
    # the switch reads as a physical thing being moved.
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    knobOffset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        self._animation.stop()
        if not self.isVisible():
            # A switch set before it is on screen has nothing to animate from.
            # Letting it start an animation anyway means the knob is still at
            # the wrong end until an event loop gets round to advancing it --
            # so a window that restores a saved "on" setting would either show
            # the switch off for a frame or, if nothing ever pumps the timer,
            # indefinitely. Snap instead; it appears already in position.
            self._set_offset(target)
            return
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(target)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:
        # setChecked emits toggled only on a real change, so a switch set to the
        # state it already holds would keep a stale offset if the animation were
        # the only thing that ever moved it.
        super().setChecked(checked)
        if self._animation.state() != QAbstractAnimation.Running:
            self._set_offset(1.0 if checked else 0.0)

    # ----------------------------------------------------------------- layout

    def _track_left(self) -> float:
        return float(self.width() - _SW_WIDTH)

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        gap = _SW_GAP if self.text() else 0
        return QSize(text_width + gap + _SW_WIDTH, max(_SW_HEIGHT, self.fontMetrics().height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        # The label is part of the control, as it is for a plain QCheckBox.
        return self.rect().contains(pos)

    # ------------------------------------------------------------------ paint

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()

        if self.text():
            colour = QColor(TEXT_PRIMARY if enabled else TEXT_MUTED)
            if not enabled:
                colour.setAlpha(120)
            painter.setPen(colour)
            painter.setFont(self.font())
            painter.drawText(
                QRectF(0, 0, self._track_left() - _SW_GAP, self.height()),
                Qt.AlignRight | Qt.AlignVCenter,
                self.text(),
            )

        track = QRectF(
            self._track_left(),
            (self.height() - _SW_HEIGHT) / 2.0,
            _SW_WIDTH,
            _SW_HEIGHT,
        )
        off = QColor(FILL)
        on = QColor(ACCENT)
        # Interpolated rather than switched at the midpoint, so the colour
        # travels with the knob instead of snapping under it.
        blend = QColor(
            round(off.red() + (on.red() - off.red()) * self._offset),
            round(off.green() + (on.green() - off.green()) * self._offset),
            round(off.blue() + (on.blue() - off.blue()) * self._offset),
        )
        if not enabled:
            blend.setAlpha(110)
        painter.setPen(Qt.NoPen)
        painter.setBrush(blend)
        painter.drawRoundedRect(track, _SW_HEIGHT / 2.0, _SW_HEIGHT / 2.0)

        diameter = _SW_HEIGHT - 2 * _SW_KNOB_INSET
        travel = _SW_WIDTH - diameter - 2 * _SW_KNOB_INSET
        knob = QRectF(
            track.left() + _SW_KNOB_INSET + travel * self._offset,
            track.top() + _SW_KNOB_INSET,
            diameter,
            diameter,
        )
        shadow = QPainterPath()
        shadow.addEllipse(knob.translated(0, 1))
        painter.fillPath(shadow, QColor(0, 0, 0, 40 if enabled else 15))
        painter.setBrush(QColor(CARD_BG))
        painter.drawEllipse(knob)
