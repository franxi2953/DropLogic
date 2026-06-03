#!/usr/bin/env py
"""
Time Series Condensate Detection Analysis

This script processes a time series of FAM images, performs condensate detection,
and generates:
1. A video with bounding box overlays
2. Histogram of condensate count evolution over time
3. Histogram of average condensate area evolution over time
"""

import sys
import os
import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from pathlib import Path
import re
from typing import List, Tuple

# Add the DropLogic library root to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

def extract_time_from_filename(filename: str) -> float:
    """Extract time in minutes from filename."""
    # Pattern: droplet001_time{X.X}min_FAM_...
    match = re.search(r'time(\d+\.?\d*)min', filename)
    if match:
        return float(match.group(1))
    return 0.0

def load_time_series(folder_path: str) -> List[Tuple[str, float, np.ndarray]]:
    """
    Load all images from time series folder, sorted by time.

    Returns:
        List of (filename, time_in_minutes, image_array) tuples
    """
    folder = Path(folder_path)
    time_series = []

    # Find all JPG files
    jpg_files = list(folder.glob('*.jpg'))
    jpg_files.sort(key=lambda x: extract_time_from_filename(x.name))

    print(f"Found {len(jpg_files)} images in time series")

    for jpg_file in jpg_files:
        time_val = extract_time_from_filename(jpg_file.name)
        image = cv2.imread(str(jpg_file))

        if image is not None:
            time_series.append((jpg_file.name, time_val, image))
            # print(".1f")
        else:
            print(f"Warning: Could not load {jpg_file.name}")

    return time_series

def calculate_box_area(bbox: Tuple[float, float, float, float]) -> float:
    """Calculate area of bounding box."""
    x1, y1, x2, y2 = bbox
    return (x2 - x1) * (y2 - y1)

def process_time_series(time_series_folder: str, output_folder: str = None):
    """Process time series and generate outputs."""

    if output_folder is None:
        output_folder = time_series_folder

    # Create output folder if it doesn't exist
    Path(output_folder).mkdir(exist_ok=True)

    # Load time series
    print("Loading time series...")
    time_series = load_time_series(time_series_folder)

    if not time_series:
        print("No images found in time series!")
        return

    # Import condensate detector and create instance once (not convenience function)
    from droplogic.utils.drop_vision import CondensateDetector
    from droplogic.utils.hardware_utils.utils import pixels_to_microns, pixels_to_volume_nl

    print("Initializing condensate detector...")
    detector = CondensateDetector()
    if not detector.is_loaded():
        print("❌ Failed to load condensate detector models!")
        return

    print("✓ Detector ready. Processing frames...")

    # Prepare data for histograms
    times = []
    condensate_counts = []
    average_lateral_sizes = []
    total_volumes = []

    # Video writer setup
    first_frame = time_series[0][2]
    height, width = first_frame.shape[:2]
    video_path = os.path.join(output_folder, 'condensate_detection_video.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(video_path, fourcc, 2.0, (width, height))  # 2 FPS

    for i, (filename, time_val, frame) in enumerate(time_series):

        # Resize frame to avoid YOLO warning (1024x1024 is multiple of 32)
        height, width = frame.shape[:2]
        # Calculate new dimensions maintaining aspect ratio, but ensure multiples of 32
        if width > height:
            new_width = 1024
            new_height = int((height * 1024) / width)
            # Make sure height is multiple of 32
            new_height = (new_height // 32) * 32
        else:
            new_height = 1024
            new_width = int((width * 1024) / height)
            # Make sure width is multiple of 32
            new_width = (new_width // 32) * 32

        resized_frame = cv2.resize(frame, (new_width, new_height))

        # Run condensate detection using the detector instance (no cropping, with NMS, no labels)
        result = detector.detect(
            resized_frame,
            crop_droplet=False,  # No cropping
            draw_labels=False,   # Clean visualization
            nms_threshold=0.6,   # Remove overlapping boxes
            return_annotated=True
        )

        # Resize the annotated frame back to original size for video
        if result.annotated_frame is not None:
            annotated_frame = cv2.resize(result.annotated_frame, (width, height))
        else:
            annotated_frame = frame.copy()

        # Increase contrast for better visualization (alpha > 1 increases contrast, beta = 0 maintains brightness)
        if annotated_frame is not None:
            contrasted_frame = cv2.convertScaleAbs(annotated_frame, alpha=1.5, beta=0)

            # Add time overlay
            time_text = f"Time: {time_val:.1f} min | Condensates: {len(result.bounding_boxes)}"
            cv2.putText(contrasted_frame, time_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

            # Write frame to video
            video_writer.write(contrasted_frame)

        # Collect data for histograms
        times.append(time_val)
        condensate_counts.append(len(result.bounding_boxes))

        # Calculate average lateral size and total volume
        if result.bounding_boxes:
            lateral_sizes = [pixels_to_microns(bbox[2] - bbox[0]) for bbox in result.bounding_boxes]  # width in microns
            avg_lateral_size = np.mean(lateral_sizes)
            
            # Calculate total volume (sum of all condensate volumes)
            volumes = [pixels_to_volume_nl(calculate_box_area(bbox)) for bbox in result.bounding_boxes]
            total_volume = np.sum(volumes)
        else:
            avg_lateral_size = 0.0
            total_volume = 0.0
            
        average_lateral_sizes.append(avg_lateral_size)
        total_volumes.append(total_volume)

    # Release video writer
    video_writer.release()
    print(f"✓ Video saved: {video_path}")

    # Create histograms
    create_histograms(times, condensate_counts, average_lateral_sizes, total_volumes, output_folder)

def create_histograms(times: List[float], counts: List[int], lateral_sizes: List[float], total_volumes: List[float], output_folder: str):
    """Create and save animated histogram video using Matplotlib with dark theme."""

    # Convert to numpy arrays
    times = np.array(times)
    counts = np.array(counts)
    lateral_sizes = np.array(lateral_sizes)
    total_volumes = np.array(total_volumes)

    # Set up the figure with dark theme
    plt.style.use('dark_background')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(7.2, 12.0))  # Increased height for more separation
    fig.subplots_adjust(hspace=0.6)  # Add vertical space between subplots

    ax1.set_title('Condensate Count', color='white', fontsize=14, pad=20)
    ax2.set_title('Average Lateral Size', color='white', fontsize=14, pad=20)
    ax3.set_title('Total Volume', color='white', fontsize=14, pad=20)

    ax1.set_xlabel('Time (minutes)', color='white')
    ax1.set_ylabel('Number of Condensates', color='white')
    ax2.set_ylabel('Average Lateral Size (μm)', color='white')
    ax3.set_ylabel('Total Volume (nL)', color='white')

    # Set x limits to full range
    xlim = (times.min(), times.max())
    ax1.set_xlim(xlim)
    ax2.set_xlim(xlim)
    ax3.set_xlim(xlim)

    # Set y limits to fixed range for proper scaling
    ax1.set_ylim(min(counts) - 0.1, max(counts) + 0.1)
    valid_lateral = lateral_sizes[lateral_sizes > 0]
    if len(valid_lateral) > 0:
        ax2.set_ylim(min(valid_lateral) - 0.1, max(valid_lateral) + 0.1)
    else:
        ax2.set_ylim(0, 1)
    valid_vol = total_volumes[total_volumes > 0]
    if len(valid_vol) > 0:
        ax3.set_ylim(min(valid_vol) - 0.001, max(valid_vol) + 0.001)
    else:
        ax3.set_ylim(0, 0.001)

    # Set colors for axes
    for ax in [ax1, ax2, ax3]:
        ax.tick_params(colors='white')
        ax.spines['bottom'].set_color('white')
        ax.spines['top'].set_color('white')
        ax.spines['right'].set_color('white')
        ax.spines['left'].set_color('white')

    # Initial empty lines with pastel colors for visibility
    line1, = ax1.plot([], [], color='#FFB6C1', linewidth=2, marker='o', markersize=5, markerfacecolor='#FFB6C1', markeredgecolor='white')  # Light pink
    line2, = ax2.plot([], [], color='#98FB98', linewidth=2, marker='s', markersize=5, markerfacecolor='#98FB98', markeredgecolor='white')  # Pale green
    line3, = ax3.plot([], [], color='#87CEEB', linewidth=2, marker='^', markersize=5, markerfacecolor='#87CEEB', markeredgecolor='white')  # Sky blue

    def init():
        line1.set_data([], [])
        line2.set_data([], [])
        line3.set_data([], [])
        return line1, line2, line3

    def animate(i):
        # Data up to frame i
        t = times[:i+1]
        c = counts[:i+1]
        l = lateral_sizes[:i+1]
        v = total_volumes[:i+1]

        # Filter zeros for lateral and volume
        valid_l = l > 0
        valid_v = v > 0

        line1.set_data(t, c)
        line2.set_data(t[valid_l], l[valid_l])
        line3.set_data(t[valid_v], v[valid_v])
        return line1, line2, line3

    # Create animation
    anim = animation.FuncAnimation(fig, animate, init_func=init, frames=len(times), interval=1000, blit=True)

    # Save as MP4
    video_path = os.path.join(output_folder, 'condensate_analysis_animation.mp4')
    try:
        writer = animation.FFMpegWriter(fps=1)
        anim.save(video_path, writer=writer)
        print(f"✓ Animation video saved: {video_path}")
    except Exception as e:
        print(f"Error saving video with ffmpeg: {e}. Trying alternative method.")
        # Fallback: save frames and use cv2
        os.makedirs(os.path.join(output_folder, 'temp_frames'), exist_ok=True)
        for i in range(len(times)):
            animate(i)
            frame_path = os.path.join(output_folder, 'temp_frames', f'frame_{i:03d}.png')
            fig.savefig(frame_path, dpi=100, bbox_inches='tight')
        # Then use cv2 to make video
        first_frame_path = os.path.join(output_folder, 'temp_frames', 'frame_000.png')
        if os.path.exists(first_frame_path):
            img = cv2.imread(first_frame_path)
            height, width = img.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(video_path, fourcc, 1.0, (width, height))
            for i in range(len(times)):
                frame_path = os.path.join(output_folder, 'temp_frames', f'frame_{i:03d}.png')
                img = cv2.imread(frame_path)
                video_writer.write(img)
            video_writer.release()
            print(f"✓ Animation video saved (fallback): {video_path}")
            # Clean up
            import shutil
            shutil.rmtree(os.path.join(output_folder, 'temp_frames'))
        else:
            print("Error: Could not create video with fallback method.")

    plt.close(fig)

    # Print summary statistics
    print("\n📊 Analysis Summary:")
    print(f"Total frames processed: {len(times)}")
    print(f"Time range: {times[0]:.1f} - {times[-1]:.1f} minutes")
    print(f"Condensate count - Mean: {np.mean(counts):.1f}, Max: {np.max(counts):.1f}, Min: {np.min(counts):.1f}")
    valid_lateral = lateral_sizes[lateral_sizes > 0]
    if len(valid_lateral) > 0:
        print(f"Average lateral size - Mean: {np.mean(valid_lateral):.1f} μm, Max: {np.max(valid_lateral):.1f} μm, Min: {np.min(valid_lateral):.1f} μm")
    valid_vol = total_volumes[total_volumes > 0]
    if len(valid_vol) > 0:
        print(f"Total volume - Mean: {np.mean(valid_vol):.3f} nL, Max: {np.max(valid_vol):.3f} nL, Min: {np.min(valid_vol):.3f} nL")

if __name__ == "__main__":
    # Process the droplet1 test time series
    time_series_folder = os.path.join(os.path.dirname(__file__), 'test_images', 'droplet1 test')

    if not os.path.exists(time_series_folder):
        print(f"Error: Time series folder not found: {time_series_folder}")
        sys.exit(1)

    print("🚀 Starting time series condensate detection analysis...")
    print(f"Input folder: {time_series_folder}")

    process_time_series(time_series_folder)

    print("✅ Analysis complete!")