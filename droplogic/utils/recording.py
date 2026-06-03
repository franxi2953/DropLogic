import os
import time

import cv2


class SegmentedVideoWriter:
    """Write frames on demand, rotating segments and maintaining a live ffconcat manifest."""

    def __init__(self, writer_name):
        self.writer_name = writer_name
        self.filename = None
        self.fps = 30
        self.segment_duration_seconds = None
        self.segment_frame_limit = None
        self.video_writer = None
        self.output_size = None
        self.segment_index = 0
        self.current_segment_filename = None
        self.current_segment_started_at = None
        self.current_segment_frame_count = 0
        self.segment_files = []
        self.concat_manifest_path = None
        self.segment_output_dir = None

    def configure(self, filename, fps, segment_duration_seconds=None, segment_frame_limit=None):
        self.filename = filename
        self.fps = fps
        self.segment_duration_seconds = (
            float(segment_duration_seconds) if segment_duration_seconds else None
        )
        self.segment_frame_limit = (
            int(segment_frame_limit) if segment_frame_limit else None
        )

    def start(self):
        self.stop()
        self.output_size = None
        self.segment_index = 0
        self.current_segment_filename = None
        self.current_segment_started_at = None
        self.current_segment_frame_count = 0
        self.segment_files = []
        self.concat_manifest_path = None
        self.segment_output_dir = None

    def stop(self):
        self._release_writer()

    def set_fps(self, fps):
        try:
            new_fps = float(fps)
        except Exception:
            return

        if new_fps <= 0:
            return

        if abs(float(self.fps or 0.0) - new_fps) < 1e-9:
            self.fps = new_fps
            return

        self.fps = new_fps
        if self.video_writer is not None:
            # Close the current segment so the next frame re-opens with the new FPS.
            self._release_writer()

    def write_frame(self, frame):
        if frame is None or self.filename is None:
            return

        if self.video_writer is None:
            self._open_writer(frame)

        if self.video_writer is None:
            return

        if self.output_size is not None and frame.shape[:2] != (self.output_size[1], self.output_size[0]):
            frame = cv2.resize(frame, self.output_size, interpolation=cv2.INTER_AREA)

        self.video_writer.write(frame)
        self.current_segment_frame_count += 1

        if self._should_rotate_segment():
            self._release_writer()

    def _release_writer(self):
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
            if self.current_segment_filename:
                print(f"Movie saved to: {self.current_segment_filename}")
                self._write_concat_manifest()
            self.current_segment_filename = None
            self.current_segment_started_at = None
            self.current_segment_frame_count = 0

    def _segmenting_enabled(self):
        return bool(
            (self.segment_duration_seconds and self.segment_duration_seconds > 0)
            or (self.segment_frame_limit and self.segment_frame_limit > 0)
        )

    def _resolve_segment_filename(self):
        if not self.filename:
            return None
        if not self._segmenting_enabled():
            return self.filename

        base_path = os.path.abspath(self.filename)
        root, ext = os.path.splitext(base_path)
        if not ext:
            ext = ".mp4"
        if self.segment_output_dir is None:
            self.segment_output_dir = f"{root}_segments"
        return os.path.join(
            self.segment_output_dir,
            f"{os.path.basename(root)}_part{self.segment_index:04d}{ext}"
        )

    def _open_writer(self, frame):
        if self.filename is None:
            return

        frame_h, frame_w = frame.shape[:2]
        self.output_size = (frame_w, frame_h)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        if self._segmenting_enabled():
            self.segment_index += 1

        target_filename = self._resolve_segment_filename()
        if target_filename is None:
            return

        output_dir = os.path.dirname(os.path.abspath(target_filename))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        self.video_writer = cv2.VideoWriter(
            target_filename,
            fourcc,
            self.fps,
            self.output_size,
        )
        self.current_segment_filename = target_filename
        self.current_segment_started_at = time.perf_counter()
        self.current_segment_frame_count = 0
        if target_filename not in self.segment_files:
            self.segment_files.append(target_filename)
        print(f"Recording movie to: {target_filename}")

    def _should_rotate_segment(self):
        if not self._segmenting_enabled() or self.video_writer is None:
            return False

        if self.segment_frame_limit and self.current_segment_frame_count >= self.segment_frame_limit:
            return True

        if self.segment_duration_seconds and self.current_segment_started_at is not None:
            elapsed = time.perf_counter() - self.current_segment_started_at
            if elapsed >= self.segment_duration_seconds:
                return True

        return False

    def _write_concat_manifest(self):
        if not self._segmenting_enabled() or not self.segment_files or not self.filename:
            return

        base_path = os.path.abspath(self.filename)
        root, _ = os.path.splitext(base_path)
        if self.segment_output_dir is None:
            self.segment_output_dir = f"{root}_segments"
        os.makedirs(self.segment_output_dir, exist_ok=True)
        manifest_path = os.path.join(
            self.segment_output_dir,
            f"{os.path.basename(root)}.ffconcat",
        )

        try:
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write("ffconcat version 1.0\n")
                for segment_file in self.segment_files:
                    normalized = os.path.basename(segment_file).replace("\\", "/").replace("'", r"'\''")
                    handle.write(f"file '{normalized}'\n")
            self.concat_manifest_path = manifest_path
            print(f"Movie segments manifest saved to: {manifest_path}")
        except Exception:
            self.concat_manifest_path = None
