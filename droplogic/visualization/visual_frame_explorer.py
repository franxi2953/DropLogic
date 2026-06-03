#!/usr/bin/env py
"""
Visual Frame Explorer for SIPP Plans

PyQt5-based GUI to visualize frames, navigate through them,
and analyze position occupancy interactively.
"""

import sys
import pickle
import numpy as np
from typing import Dict, List, Tuple, Optional
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSlider, QTextEdit, QLineEdit, QGroupBox,
                             QSplitter, QFrame, QDialog, QTextBrowser, QMenu, QComboBox)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QFont
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from droplogic.utils.advanced_drop.common import get_droplet_positions, get_droplet_vital_area


class FrameVisualizer(QWidget):
    """Widget for visualizing a single frame with zoom and pan support."""

    cursorPositionChanged = pyqtSignal(int, int)  # Signal emitted when cursor position changes (row, col)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_matrix = None
        self.droplet_positions = {}
        self.active_droplets = set()  # Track which droplets are active
        self.hovered_droplet_id = None  # Track which droplet is being hovered
        self.droplets_data = []  # Store droplet data for hover detection
        self.current_events = []  # Events for the current frame
        self.scale = 4  # pixels per cell
        self.offset_x = 0
        self.offset_y = 0
        self.dragging = False
        self.last_mouse_pos = None

        # Enable mouse tracking for pan and hover
        self.setMouseTracking(True)

    def set_frame(self, frame_matrix: np.ndarray, droplet_positions: Dict[int, Tuple[int, int]], 
                  active_droplets: set = None, droplets_data: list = None, events: list = None):
        """Set the frame data to display."""
        self.frame_matrix = frame_matrix
        self.droplet_positions = droplet_positions
        self.active_droplets = active_droplets if active_droplets is not None else set()
        self.droplets_data = droplets_data if droplets_data is not None else []
        self.current_events = events if events is not None else []
        self.update()

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        zoom_factor = 1.2
        if event.angleDelta().y() > 0:
            self.scale = min(self.scale * zoom_factor, 20)  # Max zoom
        else:
            self.scale = max(self.scale / zoom_factor, 1)  # Min zoom
        self.update()

    def mousePressEvent(self, event):
        """Start dragging."""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        """Handle dragging for panning and hover detection."""
        if self.dragging and self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.offset_x += delta.x()
            self.offset_y += delta.y()
            self.last_mouse_pos = event.pos()
            self.update()
        else:
            # Detect which droplet is being hovered
            mouse_x = event.pos().x() - self.offset_x
            mouse_y = event.pos().y() - self.offset_y
            
            col = int(mouse_x / self.scale)
            row = int(mouse_y / self.scale)
            
            # Emit cursor position signal
            if self.frame_matrix is not None:
                if (0 <= row < self.frame_matrix.shape[0] and 
                    0 <= col < self.frame_matrix.shape[1]):
                    self.cursorPositionChanged.emit(row, col)
                else:
                    self.cursorPositionChanged.emit(-1, -1)  # Out of bounds
            
            # Check if mouse is over any active droplet in the current frame
            new_hovered_id = None
            if (0 <= row < self.frame_matrix.shape[0] and 
                0 <= col < self.frame_matrix.shape[1] and 
                self.frame_matrix[row, col] == 1):  # Only if it's an activated electrode
                
                # Find which active droplet this electrode belongs to
                for d_id in self.active_droplets:
                    if d_id in self.droplet_positions:
                        pos = self.droplet_positions[d_id]
                        droplet = next((d for d in self.droplets_data if d.id == d_id), None)
                        if droplet:
                            # Check if this electrode belongs to this droplet in the current frame
                            # by checking if it's within the expected range of the droplet's position
                            expected_positions = get_droplet_positions(droplet, pos)
                            if (row, col) in expected_positions:
                                new_hovered_id = d_id
                                break
            
            if new_hovered_id != self.hovered_droplet_id:
                self.hovered_droplet_id = new_hovered_id
                self.update()

    def mouseReleaseEvent(self, event):
        """Stop dragging."""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.setCursor(Qt.ArrowCursor)

    def leaveEvent(self, event):
        """Handle mouse leaving the widget."""
        self.cursorPositionChanged.emit(-1, -1)  # Reset cursor position

    def paintEvent(self, event):
        """Draw the frame with zoom and pan."""
        if self.frame_matrix is None:
            return

        painter = QPainter(self)
        rows, cols = self.frame_matrix.shape

        # Draw events label at the top (before translation for panning)
        if self.current_events:
            event_text = " | ".join(self.current_events)
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.setPen(QColor(0, 0, 0))
            # Draw background for better readability
            text_rect = painter.boundingRect(0, 0, self.width(), 30, Qt.AlignLeft | Qt.AlignTop, event_text)
            text_rect.adjust(-5, -2, 5, 2)
            painter.fillRect(text_rect, QColor(255, 255, 200, 230))  # Light yellow background
            painter.drawText(5, 15, event_text)

        # Apply offset for panning
        painter.translate(self.offset_x, self.offset_y)

        # Get hovered droplet positions if any
        hovered_positions = set()
        if self.hovered_droplet_id is not None and self.hovered_droplet_id in self.droplet_positions:
            pos = self.droplet_positions[self.hovered_droplet_id]
            droplet = next((d for d in self.droplets_data if d.id == self.hovered_droplet_id), None)
            if droplet:
                # Instead of using get_droplet_positions, scan the frame matrix for activated electrodes
                # that are within the expected bounding box of this droplet
                row_start, col_start = pos
                # Calculate bounding box based on droplet shape
                if droplet.shape:
                    max_row_offset = max(r for r, c in droplet.shape)
                    max_col_offset = max(c for r, c in droplet.shape)
                    
                    # Scan the frame matrix within this bounding box for activated electrodes
                    for r_offset in range(max_row_offset + 1):
                        for c_offset in range(max_col_offset + 1):
                            frame_row = row_start + r_offset
                            frame_col = col_start + c_offset
                            if (0 <= frame_row < self.frame_matrix.shape[0] and 
                                0 <= frame_col < self.frame_matrix.shape[1] and
                                self.frame_matrix[frame_row, frame_col] == 1):
                                hovered_positions.add((frame_row, frame_col))

        # Draw grid
        for r in range(rows):
            for c in range(cols):
                value = self.frame_matrix[r, c]
                
                # Check if this cell is part of hovered droplet
                is_hovered = (r, c) in hovered_positions

                # Color coding
                if is_hovered:
                    color = QColor(0, 100, 255)  # Blue for hovered active droplet
                elif value == -1:  # Forbidden
                    color = QColor(128, 128, 128)  # Gray
                elif value == 1:  # Droplet body
                    color = QColor(255, 0, 0)  # Red
                elif value == 3:  # Vital area
                    color = QColor(255, 255, 0)  # Yellow
                elif value == 4:  # Reserved vital
                    color = QColor(255, 165, 0)  # Orange
                else:  # Free
                    color = QColor(255, 255, 255)  # White

                painter.fillRect(int(c * self.scale), int(r * self.scale), int(self.scale), int(self.scale), color)

                # Draw grid lines
                painter.setPen(QColor(200, 200, 200))
                painter.drawRect(int(c * self.scale), int(r * self.scale), int(self.scale), int(self.scale))

        # Draw droplet IDs (only for active droplets)
        font_size = max(8, int(self.scale * 0.5))
        painter.setFont(QFont("Arial", font_size))
        for d_id, pos in self.droplet_positions.items():
            # Only draw ID if droplet is active
            if d_id in self.active_droplets and pos is not None:
                r, c = pos
                painter.setPen(QColor(0, 0, 0))
                painter.drawText(int(c * self.scale + 2), int(r * self.scale + self.scale - 2), str(d_id))


class VisualFrameExplorer(QMainWindow):
    """Main window for visual frame exploration."""

    def __init__(self, pickle_file: str):
        super().__init__()
        self.pickle_file = pickle_file
        self.plan = None
        self.droplets = []
        self.current_frame = 0
        self.playing = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

        self.load_data()
        self.init_ui()

    def load_data(self):
        """Load plan and droplets from pickle file."""
        try:
            with open(self.pickle_file, 'rb') as f:
                data = pickle.load(f)

            # Handle both old format (dict) and new format (plan object directly)
            if isinstance(data, dict):
                self.plan = data['plan']
                self.droplets = data['droplets']
            else:
                # Assume it's a DropletPlan object directly
                self.plan = data
                self.droplets = []  # No droplets data available

            # If droplets list is empty but plan has trajectories, reconstruct minimal Droplet objects
            if (not self.droplets) and hasattr(self.plan, 'droplet_trajectories'):
                try:
                    from droplogic.utils.advanced_drop.common import Droplet
                    reconstructed = []
                    for d_id, traj in self.plan.droplet_trajectories.items():
                        if traj:
                            origin = traj[0]
                            target = traj[-1]
                            droplet = Droplet(
                                id=d_id,
                                shape={(0, 0)},
                                origin_corner=origin,
                                target_corner=target,
                                priority=0,
                                vital_space=1,
                                electrode_count=1
                            )
                            reconstructed.append(droplet)
                    self.droplets = reconstructed
                    self.droplets_reconstructed = True
                except Exception as e:
                    print(f"[WARNING] Could not reconstruct droplets: {e}")
                    self.droplets_reconstructed = False
            else:
                self.droplets_reconstructed = False

            print(f"Loaded plan with {self.plan.frame_count} frames and {len(self.droplets)} droplets")

            # Collect all events for dropdown
            self.all_events = []
            if hasattr(self.plan, 'events') and self.plan.events:
                for frame_idx, event_type, event_data in self.plan.events:
                    # Format the event description
                    if event_type == 'create':
                        droplet_id = event_data.get('droplet_id', '?')
                        desc = f"Frame {frame_idx}: CREATE D{droplet_id}"
                    elif event_type == 'remove':
                        droplet_id = event_data.get('droplet_id', '?')
                        desc = f"Frame {frame_idx}: REMOVE D{droplet_id}"
                    elif event_type == 'merge':
                        droplet_ids = event_data.get('droplet_ids', [])
                        target = event_data.get('target', '?')
                        desc = f"Frame {frame_idx}: MERGE {len(droplet_ids)} droplets → {target}"
                    elif event_type == 'init':
                        desc = f"Frame {frame_idx}: INIT"
                    elif event_type == 'relax':
                        droplet_id = event_data.get('droplet_id', '?')
                        desc = f"Frame {frame_idx}: RELAX D{droplet_id}"
                    elif event_type == 'split' or event_type == 'extraction':
                        droplet_ids = event_data.get('droplet_ids', event_data.get('new_droplet_ids', []))
                        source_id = event_data.get('source_id', event_data.get('reservoir_id', '?'))
                        desc = f"Frame {frame_idx}: {event_type.upper()} D{source_id} → {droplet_ids}"
                    else:
                        desc = f"Frame {frame_idx}: {event_type.upper()}"
                    self.all_events.append((frame_idx, desc))
        except Exception as e:
            print(f"Error loading {self.pickle_file}: {e}")
            sys.exit(1)

    def init_ui(self):
        self.setWindowTitle(f"Visual Frame Explorer - {self.pickle_file}")
        self.setGeometry(100, 100, 1200, 800)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Left panel - Controls
        control_panel = QWidget()
        control_panel.setFixedWidth(300)
        control_layout = QVBoxLayout(control_panel)

        # Frame navigation
        nav_group = QGroupBox("Frame Navigation")
        nav_layout = QVBoxLayout(nav_group)

        # Frame slider
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, self.plan.frame_count - 1)
        self.frame_slider.setValue(0)
        self.frame_slider.valueChanged.connect(self.frame_changed)
        nav_layout.addWidget(QLabel("Frame:"))
        nav_layout.addWidget(self.frame_slider)

        # Frame info
        self.frame_label = QLabel("Frame: 0 / 0")
        nav_layout.addWidget(self.frame_label)

        # Events info for current frame
        self.events_button = QPushButton("Events: None")
        self.events_button.setStyleSheet("QPushButton { background-color: #ffffcc; padding: 5px; border: 1px solid #ccccaa; text-align: left; }")
        self.events_menu = QMenu()
        for frame_idx, desc in self.all_events:
            action = self.events_menu.addAction(desc)
            action.triggered.connect(lambda checked, f=frame_idx: self.set_frame(f))
        self.events_button.setMenu(self.events_menu)
        nav_layout.addWidget(self.events_button)

        # Cursor position info
        self.cursor_label = QLabel("Cursor: --")
        self.cursor_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 3px; border: 1px solid #cccccc; font-family: monospace; }")
        nav_layout.addWidget(self.cursor_label)

        # Navigation buttons
        btn_layout = QHBoxLayout()
        prev_btn = QPushButton("◀")
        prev_btn.clicked.connect(self.prev_frame)
        play_btn = QPushButton("▶")
        play_btn.clicked.connect(self.toggle_play)
        next_btn = QPushButton("▶")
        next_btn.clicked.connect(self.next_frame)
        btn_layout.addWidget(prev_btn)
        btn_layout.addWidget(play_btn)
        btn_layout.addWidget(next_btn)
        nav_layout.addLayout(btn_layout)

        control_layout.addWidget(nav_group)

        # Conflicts box (separate from droplet info)
        conflict_group = QGroupBox("Conflicts (current frame)")
        conflict_layout = QVBoxLayout(conflict_group)

        self.conflict_text = QTextEdit()
        self.conflict_text.setReadOnly(True)
        self.conflict_text.setMinimumHeight(200)
        conflict_layout.addWidget(self.conflict_text)

        # All conflicts button (opens full-plan dialog)
        all_conflicts_btn = QPushButton("Show All Conflicts")
        all_conflicts_btn.clicked.connect(self.show_all_conflicts)
        conflict_layout.addWidget(all_conflicts_btn)

        control_layout.addWidget(conflict_group)


        # Droplet info box (keeps its scroll position across frames)
        info_group = QGroupBox("Droplet Info")
        info_layout = QVBoxLayout(info_group)

        # --- New: Search bar and selector ---
        search_layout = QHBoxLayout()
        self.droplet_search = QLineEdit()
        self.droplet_search.setPlaceholderText("Search by ID or property...")
        self.droplet_search.textChanged.connect(self.update_display)
        search_layout.addWidget(self.droplet_search)

        self.droplet_selector = QComboBox()
        self.droplet_selector.setMinimumWidth(80)
        self.droplet_selector.currentIndexChanged.connect(self.on_droplet_selected)
        search_layout.addWidget(self.droplet_selector)

        info_layout.addLayout(search_layout)

        self.info_text = QTextEdit()
        self.info_text.setMinimumHeight(400)  # Taller for droplet details
        info_layout.addWidget(self.info_text)

        # Compact droplet legend
        self.legend_label = QLabel()
        self.legend_label.setStyleSheet("font-family: monospace; font-size: 10px;")
        info_layout.addWidget(self.legend_label)

        control_layout.addWidget(info_group)

        # Track selected droplet for highlighting
        self.selected_droplet_id = None

        control_layout.addStretch()

        # Right panel - Visualization
        viz_panel = QWidget()
        viz_layout = QVBoxLayout(viz_panel)

        self.visualizer = FrameVisualizer()
        viz_layout.addWidget(self.visualizer)

        # Connect cursor position signal to update label
        self.visualizer.cursorPositionChanged.connect(self.update_cursor_position)

        # Zoom controls (compact, at bottom)
        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(5, 0, 5, 5)

        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setFixedSize(40, 25)
        zoom_in_btn.clicked.connect(self.zoom_in)

        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setFixedSize(40, 25)
        zoom_out_btn.clicked.connect(self.zoom_out)

        reset_view_btn = QPushButton("⌂")
        reset_view_btn.setFixedSize(30, 25)
        reset_view_btn.clicked.connect(self.reset_view)

        zoom_layout.addStretch()
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(reset_view_btn)

        viz_layout.addLayout(zoom_layout)

        # Add panels to main layout
        main_layout.addWidget(control_panel)
        main_layout.addWidget(viz_panel)

        # Initial display
        self.update_display()

    def on_droplet_selected(self, idx):
        # Update selected droplet ID and refresh display
        if idx >= 0:
            text = self.droplet_selector.currentText()
            try:
                self.selected_droplet_id = int(text)
            except Exception:
                self.selected_droplet_id = None
        else:
            self.selected_droplet_id = None
        self.update_display()

    def frame_changed(self, value):
        """Handle frame slider change."""
        self.current_frame = value
        self.update_display()

    def prev_frame(self):
        """Go to previous frame."""
        if self.current_frame > 0:
            self.current_frame -= 1
            self.update_display()

    def next_frame(self):
        """Go to next frame."""
        if self.current_frame < self.plan.frame_count - 1:
            self.current_frame += 1
            self.update_display()

    def toggle_play(self):
        """Toggle play/pause."""
        if self.playing:
            self.timer.stop()
            self.playing = False
        else:
            self.timer.start(500)  # 500ms per frame
            self.playing = True

    def zoom_in(self):
        """Zoom in."""
        self.visualizer.scale = min(self.visualizer.scale * 1.2, 20)
        self.visualizer.update()

    def zoom_out(self):
        """Zoom out."""
        self.visualizer.scale = max(self.visualizer.scale / 1.2, 1)
        self.visualizer.update()

    def reset_view(self):
        """Reset zoom and pan."""
        self.visualizer.scale = 4
        self.visualizer.offset_x = 0
        self.visualizer.offset_y = 0
        self.visualizer.update()

    def update_cursor_position(self, row: int, col: int):
        """Update the cursor position label."""
        if row >= 0 and col >= 0:
            self.cursor_label.setText(f"Cursor: ({row}, {col})")
        else:
            self.cursor_label.setText("Cursor: --")

    def get_droplet_color(self, droplet_id: int) -> str:
        """Get a consistent color for a droplet ID."""
        colors = [
            "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF",
            "#00FFFF", "#FFA500", "#800080", "#008000", "#800000"
        ]
        return colors[droplet_id % len(colors)]

    def show_all_conflicts(self):
        """Show a dialog with all conflicts across all frames."""
        dialog = QDialog(self)
        dialog.setWindowTitle("All Conflicts in Plan")
        dialog.setGeometry(200, 200, 800, 600)

        layout = QVBoxLayout(dialog)

        # Text browser for conflicts
        conflict_browser = QTextBrowser()
        layout.addWidget(conflict_browser)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        # Collect all conflicts
        all_conflicts = []

        for frame_idx in range(self.plan.frame_count):
            frame_matrix = self.plan.frames[frame_idx]

            # Get droplet positions for this frame
            droplet_positions = {}
            for d_id, traj in self.plan.droplet_trajectories.items():
                if frame_idx < len(traj):
                    droplet_positions[d_id] = traj[frame_idx]

            # Check for overlaps
            body_body_overlaps = []
            body_vital_overlaps = []
            vital_vital_overlaps = []

            positions_list = list(droplet_positions.items())

            for i, (id1, pos1) in enumerate(positions_list):
                droplet1 = next((d for d in self.droplets if d.id == id1), None)
                if droplet1 is None:
                    continue
                body1 = get_droplet_positions(droplet1, pos1)
                vital1 = get_droplet_vital_area(droplet1, pos1)

                for id2, pos2 in positions_list[i+1:]:
                    droplet2 = next((d for d in self.droplets if d.id == id2), None)
                    if droplet2 is None:
                        continue
                    body2 = get_droplet_positions(droplet2, pos2)
                    vital2 = get_droplet_vital_area(droplet2, pos2)

                    # Check for body-body overlap (most severe)
                    if body1 & body2:
                        body_body_overlaps.append(f"Frame {frame_idx}: 🚨 CRITICAL Body-Body D{id1} & D{id2} at {body1 & body2}")

                    # Check for body-vital overlap (severe)
                    if (body1 & vital2) or (body2 & vital1):
                        overlap_positions = (body1 & vital2) | (body2 & vital1)
                        body_vital_overlaps.append(f"Frame {frame_idx}: ⚠️ SEVERE Body-Vital D{id1} & D{id2} at {overlap_positions}")

                    # Check for vital-vital overlap (mild warning)
                    if vital1 & vital2:
                        vital_vital_overlaps.append(f"Frame {frame_idx}: ℹ️ WARNING Vital-Vital D{id1} & D{id2}")

            # Add conflicts for this frame (no frame titles)
            all_conflicts.extend(body_body_overlaps)
            all_conflicts.extend(body_vital_overlaps)
            # Ignore warnings
            # all_conflicts.extend(vital_vital_overlaps)

        # Display conflicts
        if all_conflicts:
            conflict_browser.setPlainText("\n".join(all_conflicts))
        else:
            conflict_browser.setPlainText("No conflicts found in the entire plan!")

        dialog.exec_()


    def update_display(self):
        if self.plan is None:
            return
        try:
            frame_matrix = self.plan.frames[self.current_frame]
        except Exception as e:
            print(f"Error rendering frame {self.current_frame}: {e}")
            return
        self.frame_label.setText(f"Frame: {self.current_frame} / {self.plan.frame_count - 1}")

        frame_events = []
        try:
            if hasattr(self.plan, 'event_id_per_frame') and self.plan.event_id_per_frame and self.current_frame < len(self.plan.event_id_per_frame):
                event_ids = self.plan.event_id_per_frame[self.current_frame]
                if event_ids is not None:
                    event_id_list = event_ids if isinstance(event_ids, list) else [event_ids]
                    for event_id in event_id_list:
                        if event_id is not None:
                            event_found = None
                            for event_frame, event_type, event_data in self.plan.events:
                                if isinstance(event_data, dict) and event_data.get("event_id") == event_id:
                                    event_found = (event_frame, event_type, event_data)
                                    break
                            if event_found:
                                event_frame, event_type, event_data = event_found
                                if event_type == 'create':
                                    droplet_id = event_data.get('droplet_id', '?')
                                    eid = event_data.get('event_id')
                                    text = f"CREATE D{droplet_id}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                elif event_type == 'remove':
                                    droplet_id = event_data.get('droplet_id', '?')
                                    eid = event_data.get('event_id')
                                    text = f"REMOVE D{droplet_id}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                elif event_type == 'merge':
                                    droplet_ids = event_data.get('droplet_ids', [])
                                    target = event_data.get('target', '?')
                                    frame_span = event_data.get('frame_span', '?')
                                    eid = event_data.get('event_id')
                                    text = f"MERGE {len(droplet_ids)} droplets → {target}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                elif event_type == 'init':
                                    eid = event_data.get('event_id')
                                    text = f"INIT"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                elif event_type == 'relax':
                                    droplet_id = event_data.get('droplet_id', '?')
                                    eid = event_data.get('event_id')
                                    text = f"RELAX D{droplet_id}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                elif event_type == 'split' or event_type == 'extraction':
                                    droplet_ids = event_data.get('droplet_ids', event_data.get('new_droplet_ids', []))
                                    source_id = event_data.get('source_id', event_data.get('reservoir_id', '?'))
                                    eid = event_data.get('event_id')
                                    text = f"{event_type.upper()} D{source_id} → {droplet_ids}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
                                else:
                                    eid = event_data.get('event_id')
                                    text = f"{event_type.upper()}"
                                    if eid is not None:
                                        text += f" | ID ({eid})"
                                    frame_events.append(text)
            elif hasattr(self.plan, 'events') and self.plan.events:
                for event_frame, event_type, event_data in self.plan.events:
                    if event_frame == self.current_frame:
                        if event_type == 'create':
                            droplet_id = event_data.get('droplet_id', '?')
                            eid = event_data.get('event_id')
                            text = f"CREATE D{droplet_id}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        elif event_type == 'remove':
                            droplet_id = event_data.get('droplet_id', '?')
                            eid = event_data.get('event_id')
                            text = f"REMOVE D{droplet_id}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        elif event_type == 'merge':
                            droplet_ids = event_data.get('droplet_ids', [])
                            target = event_data.get('target', '?')
                            frame_span = event_data.get('frame_span', '?')
                            eid = event_data.get('event_id')
                            text = f"MERGE {len(droplet_ids)} droplets → {target}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        elif event_type == 'init':
                            eid = event_data.get('event_id')
                            text = f"INIT"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        elif event_type == 'relax':
                            droplet_id = event_data.get('droplet_id', '?')
                            eid = event_data.get('event_id')
                            text = f"RELAX D{droplet_id}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        elif event_type == 'split' or event_type == 'extraction':
                            droplet_ids = event_data.get('droplet_ids', event_data.get('new_droplet_ids', []))
                            source_id = event_data.get('source_id', event_data.get('reservoir_id', '?'))
                            eid = event_data.get('event_id')
                            text = f"{event_type.upper()} D{source_id} → {droplet_ids}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
                        else:
                            eid = event_data.get('event_id')
                            text = f"{event_type.upper()}"
                            if eid is not None:
                                text += f" | ID ({eid})"
                            frame_events.append(text)
        except Exception as e:
            print(f"Error parsing events for frame {self.current_frame}: {e}")

        if frame_events:
            events_text = " | ".join(frame_events)
            self.events_button.setText(f"Events: {events_text}")
            self.events_button.setToolTip(events_text)
        else:
            self.events_button.setText("Events: None")
            self.events_button.setToolTip("")
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(self.current_frame)
        self.frame_slider.blockSignals(False)

        # Update label
        self.frame_label.setText(f"Frame: {self.current_frame} / {self.plan.frame_count - 1}")

        try:
            frame_matrix = self.plan.frames[self.current_frame]
        except Exception as e:
            print(f"Error rendering frame {self.current_frame}: {e}")
            return

        droplet_positions = {}
        info_lines = []
        active_droplets = set()
        try:
            if hasattr(self.plan, 'active_droplets_per_frame') and self.plan.active_droplets_per_frame:
                if self.current_frame < len(self.plan.active_droplets_per_frame):
                    active_droplets = set(self.plan.active_droplets_per_frame[self.current_frame])
        except Exception as e:
            print(f"Error reading active droplets for frame {self.current_frame}: {e}")

        for d_id, traj in self.plan.droplet_trajectories.items():
            if self.current_frame < len(traj):
                pos = traj[self.current_frame]
                droplet_positions[d_id] = pos

        all_ids = sorted(droplet_positions.keys())
        current_selector_ids = [self.droplet_selector.itemText(i) for i in range(self.droplet_selector.count())]
        if current_selector_ids != [str(i) for i in all_ids]:
            self.droplet_selector.blockSignals(True)
            self.droplet_selector.clear()
            for d_id in all_ids:
                self.droplet_selector.addItem(str(d_id))
            self.droplet_selector.blockSignals(False)
            if self.selected_droplet_id in all_ids:
                idx = all_ids.index(self.selected_droplet_id)
                self.droplet_selector.setCurrentIndex(idx)
            else:
                self.selected_droplet_id = None
                self.droplet_selector.setCurrentIndex(-1)

        search_text = self.droplet_search.text().strip().lower() if hasattr(self, 'droplet_search') else ""
        filtered_ids = all_ids
        if search_text:
            filtered_ids = [d_id for d_id in all_ids if search_text in str(d_id).lower()]

        if self.selected_droplet_id is not None and self.selected_droplet_id in all_ids:
            filtered_ids = [self.selected_droplet_id]


        formatted_lines = []
        if hasattr(self, 'droplets_reconstructed') and self.droplets_reconstructed:
            formatted_lines.append('<span style="color: orange; font-weight: bold;">[Warning] Droplet info reconstructed from plan trajectories. Shape and other properties may be default.</span>\n')
        for d_id in filtered_ids:
            pos = droplet_positions[d_id]
            color = self.get_droplet_color(d_id)
            droplet = next((d for d in self.droplets if d.id == d_id), None)
            is_active = d_id in active_droplets
            active_status = "ACTIVE" if is_active else "INACTIVE"
            formatted_lines.append("")
            formatted_lines.append(f'<b><span style="color: {color};">DROPLET {d_id} [{active_status}]</span></b>')
            if droplet:
                body = get_droplet_positions(droplet, pos)
                vital = get_droplet_vital_area(droplet, pos)
                formatted_lines.append(f'  Position: {pos}')
                formatted_lines.append(f'  Body: {sorted(body)}')
                formatted_lines.append(f'  Vital: {len(vital)} cells')
                formatted_lines.append(f'  Shape: {sorted(droplet.shape)}')
                formatted_lines.append(f'  Target: {droplet.target_corner}')
                formatted_lines.append(f'  Priority: {droplet.priority}')
                formatted_lines.append(f'  Vital space: {droplet.vital_space}')
            else:
                formatted_lines.append(f'  Position: {pos} (data not found)')
            formatted_lines.append("")

        html_content = "<pre>" + "\n".join(formatted_lines) + "</pre>"
        try:
            vscroll = self.info_text.verticalScrollBar()
            prev_value = vscroll.value()
        except Exception:
            vscroll = None
            prev_value = 0
        self.info_text.setHtml(html_content)
        if vscroll is not None:
            max_val = vscroll.maximum()
            vscroll.setValue(min(prev_value, max_val))

        legend_parts = []
        for d_id in all_ids:
            color = self.get_droplet_color(d_id)
            legend_parts.append(f'<span style="color: {color};">D{d_id}</span>')
        self.legend_label.setText("Droplets: " + " ".join(legend_parts))

        highlight_set = set([self.selected_droplet_id]) if self.selected_droplet_id in all_ids else set()
        self.visualizer.set_frame(frame_matrix, droplet_positions, active_droplets, self.droplets, frame_events)

    def set_frame(self, frame_idx):
        """Set the current frame to the specified index."""
        self.current_frame = frame_idx
        self.update_display()

    def analyze_position(self):
        """Analyze position occupancy."""
        try:
            pos_text = self.pos_input.text().strip()
            if not pos_text:
                return

            parts = pos_text.split(',')
            if len(parts) != 2:
                self.analysis_text.setPlainText("Invalid format. Use: row,col")
                return

            row, col = int(parts[0].strip()), int(parts[1].strip())
            position = (row, col)

        except ValueError:
            self.analysis_text.setPlainText("Invalid coordinates. Use: row,col")
            return

        # Analyze occupancy
        occupancy = {}

        for frame_idx in range(self.plan.frame_count):
            for d_id, traj in self.plan.droplet_trajectories.items():
                if frame_idx < len(traj):
                    pos = traj[frame_idx]
                    droplet = next((d for d in self.droplets if d.id == d_id), None)
                    if droplet is None:
                        continue

                    body = get_droplet_positions(droplet, pos)
                    vital = get_droplet_vital_area(droplet, pos)

                    if position in body:
                        if frame_idx not in occupancy:
                            occupancy[frame_idx] = []
                        occupancy[frame_idx].append((d_id, 'body'))

                    elif position in vital:
                        if frame_idx not in occupancy:
                            occupancy[frame_idx] = []
                        occupancy[frame_idx].append((d_id, 'vital'))

        # Format results
        if not occupancy:
            result = f"Position {position} is never occupied"
        else:
            lines = [f"Position {position} occupancy:"]
            for frame in sorted(occupancy.keys()):
                occupants = occupancy[frame]
                occupant_str = ", ".join(f"D{d_id}({typ})" for d_id, typ in occupants)
                lines.append(f"Frame {frame}: {occupant_str}")

                # Check conflicts
                bodies = [d_id for d_id, typ in occupants if typ == 'body']
                if len(bodies) > 1:
                    lines.append(f"  ⚠️ Body conflict: {bodies}")
                vitals = [d_id for d_id, typ in occupants if typ == 'vital']
                if len(vitals) > 1:
                    lines.append(f"  ⚠️ Vital conflict: {vitals}")

            result = "\n".join(lines)

        self.analysis_text.setPlainText(result)


def open_explorer(pickle_file_path: str = None):
    """
    Starts the visual frame explorer UI.
    Optionally accepts a path to a dumped `.pkl` file directly.
    """
    app = QApplication(sys.argv)
    
    if not pickle_file_path and len(sys.argv) > 1:
        pickle_file_path = sys.argv[1]

    window = VisualFrameExplorer(pickle_file_path)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    open_explorer()