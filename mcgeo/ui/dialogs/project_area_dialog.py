from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6 import QtWidgets, QtCore, QtGui

from ...world.overview_map import build_chunk_coverage_raster, OverviewRaster


@dataclass
class ProjectAreaSelection:
    chunk_bounds: tuple[int, int, int, int]
    use_full_world: bool


class _OverviewMapWidget(QtWidgets.QWidget):
    selection_changed = QtCore.Signal(object)  # tuple[min_cx,max_cx,min_cz,max_cz]

    def __init__(self, raster: OverviewRaster, spawn_chunk: tuple[int, int], parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(520, 360)
        self.setMouseTracking(True)
        self._raster = raster
        self._spawn_chunk = (int(spawn_chunk[0]), int(spawn_chunk[1]))
        self._selection = (raster.min_cx, raster.max_cx, raster.min_cz, raster.max_cz)
        self._drag_anchor = None
        self._image = self._build_qimage(raster)
        self._cache_rect = QtCore.QRectF()

    def _build_qimage(self, raster: OverviewRaster) -> QtGui.QImage:
        w = max(1, raster.width_px)
        h = max(1, raster.height_px)
        img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32)
        counts = raster.occupancy_counts
        max_count = max(1, max(counts) if counts else 1)

        has_surface = (
            getattr(raster, "surface_width_px", 0) > 0
            and getattr(raster, "surface_height_px", 0) > 0
            and len(getattr(raster, "surface_rgb", b"")) >= raster.surface_width_px * raster.surface_height_px * 3
            and len(getattr(raster, "surface_valid", b"")) >= raster.surface_width_px * raster.surface_height_px
            and getattr(raster, "surface_scale_chunks_per_px", 0) > 0
        )
        surf_rgb = getattr(raster, "surface_rgb", b"")
        surf_valid = getattr(raster, "surface_valid", b"")

        for z in range(h):
            row = z * w
            for x in range(w):
                c = counts[row + x]
                base_col: QtGui.QColor
                if c <= 0:
                    base_col = QtGui.QColor(26, 29, 33)
                else:
                    t = min(1.0, c / float(max_count))
                    # muted fallback heatmap
                    r0 = int(48 + 60 * t)
                    g0 = int(88 + 120 * t)
                    b0 = int(62 + 70 * t)
                    base_col = QtGui.QColor(r0, g0, b0)

                if has_surface:
                    # Map occupancy pixel center -> coarse surface guide pixel.
                    cx = raster.min_cx + x * raster.scale_chunks_per_px + (raster.scale_chunks_per_px // 2)
                    cz = raster.min_cz + z * raster.scale_chunks_per_px + (raster.scale_chunks_per_px // 2)
                    sx = (cx - raster.min_cx) // raster.surface_scale_chunks_per_px
                    sz = (cz - raster.min_cz) // raster.surface_scale_chunks_per_px
                    if 0 <= sx < raster.surface_width_px and 0 <= sz < raster.surface_height_px:
                        sidx = sz * raster.surface_width_px + sx
                        if surf_valid[sidx]:
                            r1 = surf_rgb[sidx * 3 + 0]
                            g1 = surf_rgb[sidx * 3 + 1]
                            b1 = surf_rgb[sidx * 3 + 2]
                            if c > 0:
                                # Slight occupancy shading so chunk density still reads on large worlds.
                                shade = min(1.0, c / float(max_count))
                                m = 0.78 + 0.22 * shade
                                r1 = int(max(0, min(255, r1 * m)))
                                g1 = int(max(0, min(255, g1 * m)))
                                b1 = int(max(0, min(255, b1 * m)))
                            img.setPixelColor(x, z, QtGui.QColor(r1, g1, b1))
                            continue

                img.setPixelColor(x, z, base_col)
        return img

    def selection(self) -> tuple[int, int, int, int]:
        return tuple(int(v) for v in self._selection)

    def set_selection(self, bounds: tuple[int, int, int, int]) -> None:
        min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        r = self._raster
        min_cx = max(r.min_cx, min(min_cx, r.max_cx))
        max_cx = max(r.min_cx, min(max_cx, r.max_cx))
        min_cz = max(r.min_cz, min(min_cz, r.max_cz))
        max_cz = max(r.min_cz, min(max_cz, r.max_cz))
        if min_cx > max_cx:
            min_cx, max_cx = max_cx, min_cx
        if min_cz > max_cz:
            min_cz, max_cz = max_cz, min_cz
        self._selection = (min_cx, max_cx, min_cz, max_cz)
        self.selection_changed.emit(self._selection)
        self.update()

    def _content_rect(self) -> QtCore.QRectF:
        m = 8.0
        r = QtCore.QRectF(self.rect()).adjusted(m, m, -m, -m)
        if r.width() <= 1 or r.height() <= 1:
            return r
        iw = max(1, self._image.width())
        ih = max(1, self._image.height())
        scale = min(r.width() / iw, r.height() / ih)
        w = iw * scale
        h = ih * scale
        x = r.x() + (r.width() - w) * 0.5
        y = r.y() + (r.height() - h) * 0.5
        rr = QtCore.QRectF(x, y, w, h)
        self._cache_rect = rr
        return rr

    def _chunk_from_pos(self, pos: QtCore.QPointF) -> tuple[int, int]:
        rr = self._content_rect()
        r = self._raster
        if rr.width() <= 0 or rr.height() <= 0:
            return (r.min_cx, r.min_cz)
        u = (pos.x() - rr.x()) / rr.width()
        v = (pos.y() - rr.y()) / rr.height()
        u = max(0.0, min(0.999999, u))
        v = max(0.0, min(0.999999, v))
        cx = r.min_cx + int(u * (r.max_cx - r.min_cx + 1))
        cz = r.min_cz + int(v * (r.max_cz - r.min_cz + 1))
        return (cx, cz)

    def _rect_from_selection(self) -> QtCore.QRectF:
        rr = self._content_rect()
        if rr.width() <= 0 or rr.height() <= 0:
            return QtCore.QRectF()
        r = self._raster
        min_cx, max_cx, min_cz, max_cz = self._selection
        cx_span = max(1, r.max_cx - r.min_cx + 1)
        cz_span = max(1, r.max_cz - r.min_cz + 1)
        x0 = (min_cx - r.min_cx) / cx_span
        x1 = (max_cx + 1 - r.min_cx) / cx_span
        z0 = (min_cz - r.min_cz) / cz_span
        z1 = (max_cz + 1 - r.min_cz) / cz_span
        return QtCore.QRectF(
            rr.x() + x0 * rr.width(),
            rr.y() + z0 * rr.height(),
            max(1.0, (x1 - x0) * rr.width()),
            max(1.0, (z1 - z0) * rr.height()),
        )

    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() != QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        c = self._chunk_from_pos(e.position())
        self._drag_anchor = c
        self.set_selection((c[0], c[0], c[1], c[1]))
        e.accept()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:
        if self._drag_anchor is None or not (e.buttons() & QtCore.Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(e)
        c = self._chunk_from_pos(e.position())
        ax, az = self._drag_anchor
        self.set_selection((min(ax, c[0]), max(ax, c[0]), min(az, c[1]), max(az, c[1])))
        e.accept()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_anchor = None
            e.accept()
            return
        return super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QtGui.QColor(30, 33, 38))
        rr = self._content_rect()
        p.fillRect(rr, QtGui.QColor(18, 20, 24))
        p.drawImage(rr, self._image)

        # Border
        p.setPen(QtGui.QPen(QtGui.QColor(92, 102, 118), 1.0))
        p.drawRect(rr)

        # Spawn marker
        sx, sz = self._spawn_chunk
        r = self._raster
        if r.min_cx <= sx <= r.max_cx and r.min_cz <= sz <= r.max_cz:
            cx_span = max(1, r.max_cx - r.min_cx + 1)
            cz_span = max(1, r.max_cz - r.min_cz + 1)
            px = rr.x() + ((sx - r.min_cx) + 0.5) / cx_span * rr.width()
            pz = rr.y() + ((sz - r.min_cz) + 0.5) / cz_span * rr.height()
            p.setPen(QtGui.QPen(QtGui.QColor(255, 200, 80), 1.5))
            p.drawLine(QtCore.QPointF(px - 5, pz), QtCore.QPointF(px + 5, pz))
            p.drawLine(QtCore.QPointF(px, pz - 5), QtCore.QPointF(px, pz + 5))

        # Selection overlay
        sr = self._rect_from_selection()
        p.fillRect(sr, QtGui.QColor(86, 149, 255, 52))
        p.setPen(QtGui.QPen(QtGui.QColor(110, 170, 255), 2.0))
        p.drawRect(sr)

        # Label badge
        min_cx, max_cx, min_cz, max_cz = self._selection
        txt = f'Selection: {max_cx-min_cx+1}×{max_cz-min_cz+1} chunks'
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(txt) + 14
        th = fm.height() + 8
        badge = QtCore.QRectF(rr.x() + 8, rr.y() + 8, tw, th)
        p.fillRect(badge, QtGui.QColor(24, 28, 34, 210))
        p.setPen(QtGui.QPen(QtGui.QColor(118, 178, 255), 1.0))
        p.drawRect(badge)
        p.setPen(QtGui.QPen(QtGui.QColor(235, 241, 250), 1.0))
        p.drawText(badge.adjusted(7, 0, -7, 0), QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft, txt)


class ProjectAreaDialog(QtWidgets.QDialog):
    def __init__(self, world_index, current_selection: Optional[tuple[int, int, int, int]] = None, *, raster: Optional[OverviewRaster] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Project Settings • Edit Area')
        self.setModal(True)
        self.resize(980, 700)
        self._world_index = world_index
        self._raster = raster if raster is not None else build_chunk_coverage_raster(world_index, max_dim_px=1024)
        self._sync_guard = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QtWidgets.QLabel('Choose the world area to edit')
        title.setObjectName('PanelTitle')
        layout.addWidget(title)
        subtitle = QtWidgets.QLabel(
            'This 2D map is for project setup only. It shows a fast world overview plus a coarse top-surface color guide so you can see where you are before entering the 3D editor. It does not modify the world.'
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName('SubtleHint')
        layout.addWidget(subtitle)

        self.map_widget = _OverviewMapWidget(self._raster, tuple(world_index.spawn_chunk))
        layout.addWidget(self.map_widget, 1)

        controls = QtWidgets.QGroupBox('Selection')
        g = QtWidgets.QGridLayout(controls)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)

        # Internal selection state still uses spin boxes for compatibility with existing methods,
        # but they are hidden to keep this dialog map-first and simple.
        self.min_cx = QtWidgets.QSpinBox(); self.max_cx = QtWidgets.QSpinBox()
        self.min_cz = QtWidgets.QSpinBox(); self.max_cz = QtWidgets.QSpinBox()
        for sb in (self.min_cx, self.max_cx, self.min_cz, self.max_cz):
            sb.setRange(-2_000_000, 2_000_000)
            sb.hide()

        hint = QtWidgets.QLabel('Drag a rectangle on the map to choose the edit area.')
        hint.setObjectName('SubtleHint')
        g.addWidget(hint, 0, 0, 1, 4)

        self.btn_recommended = QtWidgets.QPushButton('Recommended (spawn area)')
        self.btn_full = QtWidgets.QPushButton('Full world')
        self.btn_spawn_single = QtWidgets.QPushButton('1 chunk @ spawn')
        self.use_full_world = QtWidgets.QCheckBox('Mark as full-world project area')
        self.use_full_world.setToolTip('Convenience flag for saved project settings. Renderer is still chunk-streamed.')

        g.addWidget(self.btn_recommended, 1, 0, 1, 2)
        g.addWidget(self.btn_full, 1, 2, 1, 2)
        g.addWidget(self.btn_spawn_single, 2, 0, 1, 2)
        g.addWidget(self.use_full_world, 2, 2, 1, 2)

        self.summary = QtWidgets.QLabel('')
        self.summary.setWordWrap(True)
        self.summary.setObjectName('SubtleHint')
        g.addWidget(self.summary, 3, 0, 1, 4)
        layout.addWidget(controls)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.map_widget.selection_changed.connect(self._on_map_selection_changed)
        for sb in (self.min_cx, self.max_cx, self.min_cz, self.max_cz):
            sb.valueChanged.connect(self._on_spin_changed)

        self.btn_recommended.clicked.connect(self._set_recommended_selection)
        self.btn_full.clicked.connect(self._set_full_world_selection)
        self.btn_spawn_single.clicked.connect(self._set_spawn_chunk_selection)
        self.use_full_world.toggled.connect(self._refresh_summary)

        if current_selection is not None:
            self.set_selection(current_selection)
        else:
            self._set_recommended_selection()

    def _world_bounds(self) -> tuple[int, int, int, int]:
        r = self._raster
        return (r.min_cx, r.max_cx, r.min_cz, r.max_cz)

    def _default_recommended_bounds(self) -> tuple[int, int, int, int]:
        min_cx, max_cx, min_cz, max_cz = self._world_bounds()
        sx, sz = [int(v) for v in self._world_index.spawn_chunk]
        # Default recommendation: ~96x96 chunks (1536x1536 blocks) unless world is smaller.
        size = 96
        half = size // 2
        if (max_cx - min_cx + 1) <= size and (max_cz - min_cz + 1) <= size:
            return (min_cx, max_cx, min_cz, max_cz)
        a = sx - half; b = sx + half - 1
        c = sz - half; d = sz + half - 1
        if a < min_cx:
            b += (min_cx - a); a = min_cx
        if b > max_cx:
            a -= (b - max_cx); b = max_cx
        if c < min_cz:
            d += (min_cz - c); c = min_cz
        if d > max_cz:
            c -= (d - max_cz); d = max_cz
        a = max(min_cx, a); b = min(max_cx, b)
        c = max(min_cz, c); d = min(max_cz, d)
        return (a, b, c, d)

    def _set_recommended_selection(self) -> None:
        self.use_full_world.setChecked(False)
        self.set_selection(self._default_recommended_bounds())

    def _set_full_world_selection(self) -> None:
        self.use_full_world.setChecked(True)
        self.set_selection(self._world_bounds())

    def _set_spawn_chunk_selection(self) -> None:
        self.use_full_world.setChecked(False)
        sx, sz = [int(v) for v in self._world_index.spawn_chunk]
        self.set_selection((sx, sx, sz, sz))

    def _selection_tuple(self) -> tuple[int, int, int, int]:
        vals = [self.min_cx.value(), self.max_cx.value(), self.min_cz.value(), self.max_cz.value()]
        min_cx, max_cx, min_cz, max_cz = [int(v) for v in vals]
        if min_cx > max_cx:
            min_cx, max_cx = max_cx, min_cx
        if min_cz > max_cz:
            min_cz, max_cz = max_cz, min_cz
        r = self._raster
        min_cx = max(r.min_cx, min(min_cx, r.max_cx))
        max_cx = max(r.min_cx, min(max_cx, r.max_cx))
        min_cz = max(r.min_cz, min(min_cz, r.max_cz))
        max_cz = max(r.min_cz, min(max_cz, r.max_cz))
        return (min_cx, max_cx, min_cz, max_cz)

    def set_selection(self, bounds: tuple[int, int, int, int]) -> None:
        min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        self._sync_guard = True
        try:
            self.min_cx.setValue(min_cx)
            self.max_cx.setValue(max_cx)
            self.min_cz.setValue(min_cz)
            self.max_cz.setValue(max_cz)
        finally:
            self._sync_guard = False
        b = self._selection_tuple()
        self.map_widget.set_selection(b)
        self._refresh_summary()

    @QtCore.Slot(object)
    def _on_map_selection_changed(self, bounds: object) -> None:
        if self._sync_guard:
            return
        try:
            min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        except Exception:
            return
        self._sync_guard = True
        try:
            self.min_cx.setValue(min_cx)
            self.max_cx.setValue(max_cx)
            self.min_cz.setValue(min_cz)
            self.max_cz.setValue(max_cz)
        finally:
            self._sync_guard = False
        self._refresh_summary()

    @QtCore.Slot()
    def _on_spin_changed(self) -> None:
        if self._sync_guard:
            return
        b = self._selection_tuple()
        self.map_widget.set_selection(b)
        self._refresh_summary()

    @QtCore.Slot()
    def _refresh_summary(self) -> None:
        min_cx, max_cx, min_cz, max_cz = self._selection_tuple()
        w = max_cx - min_cx + 1
        h = max_cz - min_cz + 1
        blocks_x = w * 16
        blocks_z = h * 16
        total = w * h
        world_w = self._raster.max_cx - self._raster.min_cx + 1
        world_h = self._raster.max_cz - self._raster.min_cz + 1
        full = (w == world_w and h == world_h and min_cx == self._raster.min_cx and min_cz == self._raster.min_cz)
        if full and not self.use_full_world.isChecked():
            # keep checkbox in sync if user drag-selects the full bounds
            self.use_full_world.blockSignals(True)
            self.use_full_world.setChecked(True)
            self.use_full_world.blockSignals(False)
        self.summary.setText(
            f'Selected area: {w} × {h} chunks ({total:,}) • Approx footprint: {blocks_x:,} × {blocks_z:,} blocks • 'f'World size: {world_w} × {world_h} chunks • Drag on the map to adjust'
        )

    def selection_result(self) -> ProjectAreaSelection:
        b = self._selection_tuple()
        full_world = bool(self.use_full_world.isChecked()) or b == self._world_bounds()
        return ProjectAreaSelection(chunk_bounds=b, use_full_world=full_world)

    @staticmethod
    def _build_raster_with_progress(world_index, parent=None) -> OverviewRaster:
        dlg = QtWidgets.QProgressDialog("Building detailed 2D world map…", None, 0, 1, parent)
        dlg.setWindowTitle("Preparing project area map")
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        def _progress(done: int, total: int, message: str) -> None:
            try:
                dlg.setMaximum(max(1, int(total)))
                dlg.setValue(max(0, min(int(done), int(total))))
                dlg.setLabelText(str(message))
            except Exception:
                pass
            QtWidgets.QApplication.processEvents()

        dlg.show()
        QtWidgets.QApplication.processEvents()
        try:
            return build_chunk_coverage_raster(world_index, max_dim_px=1024, progress_cb=_progress)
        finally:
            try:
                dlg.setValue(dlg.maximum())
                dlg.close()
            except Exception:
                pass

    @staticmethod
    def get_selection(world_index, current_selection: Optional[tuple[int, int, int, int]] = None, parent=None) -> Optional[ProjectAreaSelection]:
        raster = ProjectAreaDialog._build_raster_with_progress(world_index, parent=parent)
        dlg = ProjectAreaDialog(world_index=world_index, current_selection=current_selection, raster=raster, parent=parent)
        if dlg.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return None
        return dlg.selection_result()
