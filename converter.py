#!/usr/bin/env python3
"""
DaVinci Resolve Project (.drp/.drt) to Blender (.blend) Converter

This script converts DaVinci Resolve project files (.drp) and timeline files (.drt) 
to Blender project files (.blend). It extracts timeline information, clips, transitions, 
effects, and other metadata from the DRP/DRT XML structure and reconstructs them as 
Blender scene elements.

Supported Input Formats:
    - .drp: DaVinci Resolve Project Files (PRIMARY)
    - .drt: DaVinci Resolve Timeline Files (LEGACY)

Usage:
    python drt_to_blend_converter.py input_file.drp output_file.blend [--verbose] [--skip-media] [--fps 24]
    python drt_to_blend_converter.py input_file.drt output_file.blend [--verbose] [--skip-media] [--fps 24]

Author: Timeline Converter
Version: 2.0.0
"""

import os
import sys
import json
import math
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import xml.etree.ElementTree as ET
from datetime import timedelta
import hashlib
import struct

# Try to import bpy (Blender Python API)
try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False
    print("Warning: bpy not available. Install Blender to enable full .blend export.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ClipType(Enum):
    """Types of clips in the timeline."""
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TITLE = "title"
    ADJUSTMENT = "adjustment"
    UNKNOWN = "unknown"


class TransitionType(Enum):
    """Types of transitions."""
    CUT = "cut"
    DISSOLVE = "dissolve"
    WIPE = "wipe"
    PUSH = "push"
    FADE = "fade"
    CUSTOM = "custom"


class EffectType(Enum):
    """Types of effects."""
    COLOR_CORRECTION = "color_correction"
    BLUR = "blur"
    TRANSFORM = "transform"
    SPEED = "speed"
    OPACITY = "opacity"
    SCALE = "scale"
    ROTATION = "rotation"
    CUSTOM = "custom"


@dataclass
class TimelineFrame:
    """Represents a frame/time position."""
    frames: int
    fps: float = 24.0

    @property
    def seconds(self) -> float:
        """Convert frames to seconds."""
        return self.frames / self.fps

    @property
    def timecode(self) -> str:
        """Generate timecode string (HH:MM:SS:FF)."""
        total_seconds = self.seconds
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        frames = int(self.frames % int(self.fps))
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


@dataclass
class ClipProperties:
    """Properties of a media clip."""
    clip_id: str
    name: str
    type: ClipType
    start_frame: int
    end_frame: int
    duration: int
    media_path: Optional[str] = None
    opacity: float = 1.0
    speed: float = 1.0
    reversed: bool = False
    in_point: int = 0
    out_point: int = 0
    markers: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.markers is None:
            self.markers = []


@dataclass
class TransitionProperties:
    """Properties of a transition."""
    transition_id: str
    type: TransitionType
    duration: int
    start_frame: int
    end_frame: int
    from_clip: Optional[str] = None
    to_clip: Optional[str] = None
    params: Dict[str, Any] = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}


@dataclass
class EffectProperties:
    """Properties of an effect."""
    effect_id: str
    name: str
    type: EffectType
    clip_id: str
    start_frame: int
    duration: int
    params: Dict[str, Any] = None
    keyframes: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}
        if self.keyframes is None:
            self.keyframes = []


@dataclass
class AudioTrackInfo:
    """Information about an audio track."""
    track_id: str
    index: int
    name: str
    volume: float = 1.0
    pan: float = 0.0
    muted: bool = False
    locked: bool = False


@dataclass
class VideoTrackInfo:
    """Information about a video track."""
    track_id: str
    index: int
    name: str
    visibility: bool = True
    locked: bool = False
    opacity: float = 1.0


@dataclass
class TimelineMetadata:
    """Metadata about the timeline."""
    name: str
    fps: float
    resolution_width: int
    resolution_height: int
    duration_frames: int
    color_space: str = "Linear"
    gamma: float = 2.2
    pixel_aspect_ratio: float = 1.0
    start_timecode: str = "00:00:00:00"


class DRTFileParser:
    """Parser for DaVinci Resolve XML files (.drp and .drt formats)."""

    def __init__(self, file_path: str, verbose: bool = False):
        """Initialize the DRP/DRT parser.
        
        Args:
            file_path: Path to the .drp or .drt XML file
            verbose: Enable verbose logging
        """
        self.file_path = Path(file_path)
        self.verbose = verbose
        self.tree = None
        self.root = None
        self.file_format = self._detect_format()
        self.clips: Dict[str, ClipProperties] = {}
        self.transitions: Dict[str, TransitionProperties] = {}
        self.effects: Dict[str, EffectProperties] = {}
        self.video_tracks: List[VideoTrackInfo] = []
        self.audio_tracks: List[AudioTrackInfo] = []
        self.metadata: Optional[TimelineMetadata] = None

        if self.verbose:
            logger.setLevel(logging.DEBUG)
    
    def _detect_format(self) -> str:
        """Detect file format from extension.
        
        Returns:
            'drp', 'drt', or 'unknown'
        """
        suffix = self.file_path.suffix.lower()
        if suffix == '.drp':
            return 'drp'
        elif suffix == '.drt':
            return 'drt'
        else:
            return 'unknown'

    def parse(self) -> bool:
        """Parse the DRT file.
        
        Returns:
            True if parsing was successful, False otherwise
        """
        try:
            if not self.file_path.exists():
                logger.error(f"File not found: {self.file_path}")
                return False

            logger.info(f"Parsing DRT file: {self.file_path}")
            self.tree = ET.parse(self.file_path)
            self.root = self.tree.getroot()

            # Extract metadata
            self._parse_metadata()

            # Extract clips
            self._parse_clips()

            # Extract transitions
            self._parse_transitions()

            # Extract effects
            self._parse_effects()

            # Extract audio/video tracks
            self._parse_tracks()

            logger.info(f"Successfully parsed DRT file")
            logger.info(f"Found {len(self.clips)} clips, {len(self.transitions)} transitions, "
                       f"{len(self.effects)} effects")
            return True

        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error parsing DRT file: {e}")
            return False

    def _parse_metadata(self) -> None:
        """Extract timeline metadata."""
        try:
            # Look for timeline/project metadata
            timeline = self.root.find('.//Timeline') or self.root.find('.//timeline')
            
            if timeline is not None:
                name = timeline.get('name', 'Untitled Timeline')
                fps = float(timeline.get('fps', 24.0))
                width = int(timeline.get('width', 1920))
                height = int(timeline.get('height', 1080))
                duration = int(timeline.get('duration', 0))
                
                # Try to get color space info
                color_space = timeline.get('colorSpace', 'Linear')
                start_timecode = timeline.get('startTimecode', '00:00:00:00')
                
                self.metadata = TimelineMetadata(
                    name=name,
                    fps=fps,
                    resolution_width=width,
                    resolution_height=height,
                    duration_frames=duration,
                    color_space=color_space,
                    start_timecode=start_timecode
                )
                
                logger.info(f"Timeline: {name} ({width}x{height}) @ {fps}fps, "
                           f"Duration: {duration} frames")
            else:
                # Create default metadata
                self.metadata = TimelineMetadata(
                    name="Imported Timeline",
                    fps=24.0,
                    resolution_width=1920,
                    resolution_height=1080,
                    duration_frames=0
                )
                logger.warning("Could not find timeline metadata, using defaults")

        except Exception as e:
            logger.error(f"Error parsing metadata: {e}")
            self.metadata = TimelineMetadata(
                name="Imported Timeline",
                fps=24.0,
                resolution_width=1920,
                resolution_height=1080,
                duration_frames=0
            )

    def _parse_clips(self) -> None:
        """Extract clips from the timeline."""
        try:
            # Look for clips in various possible locations
            clip_elements = (
                self.root.findall('.//Clip') + 
                self.root.findall('.//clip') +
                self.root.findall('.//Media') +
                self.root.findall('.//media')
            )

            for clip_elem in clip_elements:
                clip_id = clip_elem.get('id', f'clip_{len(self.clips)}')
                name = clip_elem.get('name', clip_id)
                start = int(clip_elem.get('start', 0))
                end = int(clip_elem.get('end', 0))
                duration = end - start
                media_path = clip_elem.get('path') or clip_elem.get('src')

                # Determine clip type
                clip_type_str = clip_elem.get('type', 'video').lower()
                try:
                    clip_type = ClipType(clip_type_str)
                except ValueError:
                    clip_type = ClipType.UNKNOWN

                # Extract optional properties
                opacity = float(clip_elem.get('opacity', 1.0))
                speed = float(clip_elem.get('speed', 1.0))
                reversed_val = clip_elem.get('reversed', 'false').lower() == 'true'
                in_point = int(clip_elem.get('inPoint', 0))
                out_point = int(clip_elem.get('outPoint', 0))

                # Extract markers
                markers = []
                for marker_elem in clip_elem.findall('.//Marker') + clip_elem.findall('.//marker'):
                    marker = {
                        'name': marker_elem.get('name', 'Marker'),
                        'color': marker_elem.get('color', 'red'),
                        'frame': int(marker_elem.get('frame', 0)),
                        'comment': marker_elem.get('comment', '')
                    }
                    markers.append(marker)

                clip = ClipProperties(
                    clip_id=clip_id,
                    name=name,
                    type=clip_type,
                    start_frame=start,
                    end_frame=end,
                    duration=duration,
                    media_path=media_path,
                    opacity=opacity,
                    speed=speed,
                    reversed=reversed_val,
                    in_point=in_point,
                    out_point=out_point,
                    markers=markers
                )

                self.clips[clip_id] = clip
                logger.debug(f"Parsed clip: {name} ({clip_type.value}) @ {start}-{end}")

        except Exception as e:
            logger.error(f"Error parsing clips: {e}")

    def _parse_transitions(self) -> None:
        """Extract transitions from the timeline."""
        try:
            transition_elements = (
                self.root.findall('.//Transition') +
                self.root.findall('.//transition')
            )

            for trans_elem in transition_elements:
                trans_id = trans_elem.get('id', f'transition_{len(self.transitions)}')
                trans_type_str = trans_elem.get('type', 'cut').lower()
                
                try:
                    trans_type = TransitionType(trans_type_str)
                except ValueError:
                    trans_type = TransitionType.CUSTOM

                duration = int(trans_elem.get('duration', 0))
                start = int(trans_elem.get('start', 0))
                end = start + duration
                from_clip = trans_elem.get('fromClip')
                to_clip = trans_elem.get('toClip')

                # Extract transition parameters
                params = {}
                for param_elem in trans_elem.findall('.//Param') + trans_elem.findall('.//param'):
                    param_name = param_elem.get('name', 'unknown')
                    param_value = param_elem.get('value', '')
                    try:
                        params[param_name] = float(param_value)
                    except ValueError:
                        params[param_name] = param_value

                transition = TransitionProperties(
                    transition_id=trans_id,
                    type=trans_type,
                    duration=duration,
                    start_frame=start,
                    end_frame=end,
                    from_clip=from_clip,
                    to_clip=to_clip,
                    params=params
                )

                self.transitions[trans_id] = transition
                logger.debug(f"Parsed transition: {trans_type.value} @ {start}")

        except Exception as e:
            logger.error(f"Error parsing transitions: {e}")

    def _parse_effects(self) -> None:
        """Extract effects from the timeline."""
        try:
            effect_elements = (
                self.root.findall('.//Effect') +
                self.root.findall('.//effect')
            )

            for effect_elem in effect_elements:
                effect_id = effect_elem.get('id', f'effect_{len(self.effects)}')
                name = effect_elem.get('name', effect_id)
                effect_type_str = effect_elem.get('type', 'custom').lower()
                
                try:
                    effect_type = EffectType(effect_type_str)
                except ValueError:
                    effect_type = EffectType.CUSTOM

                clip_id = effect_elem.get('clipId')
                start = int(effect_elem.get('start', 0))
                duration = int(effect_elem.get('duration', 0))

                # Extract effect parameters
                params = {}
                for param_elem in effect_elem.findall('.//Param') + effect_elem.findall('.//param'):
                    param_name = param_elem.get('name', 'unknown')
                    param_value = param_elem.get('value', '')
                    try:
                        params[param_name] = float(param_value)
                    except ValueError:
                        params[param_name] = param_value

                # Extract keyframes
                keyframes = []
                for keyframe_elem in effect_elem.findall('.//Keyframe') + effect_elem.findall('.//keyframe'):
                    keyframe = {
                        'frame': int(keyframe_elem.get('frame', 0)),
                        'value': float(keyframe_elem.get('value', 0.0)),
                        'interpolation': keyframe_elem.get('interpolation', 'linear')
                    }
                    keyframes.append(keyframe)

                effect = EffectProperties(
                    effect_id=effect_id,
                    name=name,
                    type=effect_type,
                    clip_id=clip_id,
                    start_frame=start,
                    duration=duration,
                    params=params,
                    keyframes=keyframes
                )

                self.effects[effect_id] = effect
                logger.debug(f"Parsed effect: {name} ({effect_type.value}) on {clip_id}")

        except Exception as e:
            logger.error(f"Error parsing effects: {e}")

    def _parse_tracks(self) -> None:
        """Extract audio and video track information."""
        try:
            # Parse video tracks
            video_track_elements = (
                self.root.findall('.//VideoTrack') +
                self.root.findall('.//videoTrack')
            )

            for idx, track_elem in enumerate(video_track_elements):
                track_id = track_elem.get('id', f'video_track_{idx}')
                name = track_elem.get('name', f'Video Track {idx + 1}')
                visibility = track_elem.get('visible', 'true').lower() == 'true'
                locked = track_elem.get('locked', 'false').lower() == 'true'
                opacity = float(track_elem.get('opacity', 1.0))

                track = VideoTrackInfo(
                    track_id=track_id,
                    index=idx,
                    name=name,
                    visibility=visibility,
                    locked=locked,
                    opacity=opacity
                )
                self.video_tracks.append(track)

            # Parse audio tracks
            audio_track_elements = (
                self.root.findall('.//AudioTrack') +
                self.root.findall('.//audioTrack')
            )

            for idx, track_elem in enumerate(audio_track_elements):
                track_id = track_elem.get('id', f'audio_track_{idx}')
                name = track_elem.get('name', f'Audio Track {idx + 1}')
                volume = float(track_elem.get('volume', 1.0))
                pan = float(track_elem.get('pan', 0.0))
                muted = track_elem.get('muted', 'false').lower() == 'true'
                locked = track_elem.get('locked', 'false').lower() == 'true'

                track = AudioTrackInfo(
                    track_id=track_id,
                    index=idx,
                    name=name,
                    volume=volume,
                    pan=pan,
                    muted=muted,
                    locked=locked
                )
                self.audio_tracks.append(track)

            logger.info(f"Found {len(self.video_tracks)} video tracks and "
                       f"{len(self.audio_tracks)} audio tracks")

        except Exception as e:
            logger.error(f"Error parsing tracks: {e}")


class BlenderSceneBuilder:
    """Builder for creating Blender scenes from timeline data."""

    def __init__(self, metadata: TimelineMetadata, verbose: bool = False):
        """Initialize the Blender scene builder.
        
        Args:
            metadata: Timeline metadata
            verbose: Enable verbose logging
        """
        self.metadata = metadata
        self.verbose = verbose
        self.scene = None
        self.strips = []
        self.objects = []

    def build_scene(self) -> bool:
        """Build the Blender scene.
        
        Returns:
            True if successful, False otherwise
        """
        if not BLENDER_AVAILABLE:
            logger.error("Blender (bpy) not available. Cannot build scene.")
            return False

        try:
            logger.info("Building Blender scene...")

            # Create new scene
            bpy.ops.scene.new(type='EMPTY')
            self.scene = bpy.context.scene

            # Set scene properties
            self._configure_scene()

            logger.info("Scene built successfully")
            return True

        except Exception as e:
            logger.error(f"Error building scene: {e}")
            return False

    def _configure_scene(self) -> None:
        """Configure scene properties from metadata."""
        self.scene.name = self.metadata.name
        self.scene.render.fps = int(self.metadata.fps)
        self.scene.render.resolution_x = self.metadata.resolution_width
        self.scene.render.resolution_y = self.metadata.resolution_height
        self.scene.frame_end = self.metadata.duration_frames

        # Configure color management
        self.scene.view_settings.view_transform = 'Standard'
        self.scene.render.engine = 'CYCLES'

        logger.debug(f"Configured scene: {self.metadata.resolution_width}x"
                    f"{self.metadata.resolution_height} @ {self.metadata.fps}fps")

    def add_clip(self, clip: ClipProperties) -> Optional[Any]:
        """Add a clip to the scene.
        
        Args:
            clip: Clip properties
            
        Returns:
            The created object or None if failed
        """
        try:
            if clip.type == ClipType.VIDEO or clip.type == ClipType.IMAGE:
                if clip.media_path and os.path.exists(clip.media_path):
                    return self._add_video_clip(clip)
            elif clip.type == ClipType.TITLE:
                return self._add_title_clip(clip)
            elif clip.type == ClipType.AUDIO:
                return self._add_audio_clip(clip)
            else:
                logger.warning(f"Unsupported clip type: {clip.type}")
                return None

        except Exception as e:
            logger.error(f"Error adding clip {clip.name}: {e}")
            return None

    def _add_video_clip(self, clip: ClipProperties) -> Optional[Any]:
        """Add a video clip to the scene."""
        try:
            # Create an empty object to represent the clip
            bpy.ops.object.empty_add(location=(0, 0, 0))
            obj = bpy.context.active_object
            obj.name = clip.name

            # Store clip data as custom properties
            obj['clip_id'] = clip.clip_id
            obj['clip_type'] = clip.type.value
            obj['start_frame'] = clip.start_frame
            obj['end_frame'] = clip.end_frame
            obj['duration'] = clip.duration
            obj['media_path'] = clip.media_path or ''
            obj['opacity'] = clip.opacity
            obj['speed'] = clip.speed

            # Position on timeline
            obj.location.x = clip.start_frame * 0.01
            obj.scale.x = clip.duration * 0.01

            self.objects.append(obj)
            logger.debug(f"Added video clip: {clip.name}")
            return obj

        except Exception as e:
            logger.error(f"Error adding video clip: {e}")
            return None

    def _add_title_clip(self, clip: ClipProperties) -> Optional[Any]:
        """Add a title/text clip to the scene."""
        try:
            bpy.ops.object.text_add(location=(0, 0, 0))
            obj = bpy.context.active_object
            obj.name = clip.name
            obj.data.body = clip.name

            # Store clip data
            obj['clip_id'] = clip.clip_id
            obj['clip_type'] = clip.type.value
            obj['start_frame'] = clip.start_frame
            obj['end_frame'] = clip.end_frame

            self.objects.append(obj)
            logger.debug(f"Added title clip: {clip.name}")
            return obj

        except Exception as e:
            logger.error(f"Error adding title clip: {e}")
            return None

    def _add_audio_clip(self, clip: ClipProperties) -> Optional[Any]:
        """Add an audio clip to the scene."""
        try:
            if not BLENDER_AVAILABLE:
                return None

            bpy.ops.object.empty_add(location=(0, 1, 0))
            obj = bpy.context.active_object
            obj.name = clip.name
            obj.empty_display_type = 'CUBE'  # Use CUBE instead of SPEAKER (more compatible)

            obj['clip_id'] = clip.clip_id
            obj['clip_type'] = clip.type.value
            obj['start_frame'] = clip.start_frame
            obj['end_frame'] = clip.end_frame
            obj['media_path'] = clip.media_path or ''

            self.objects.append(obj)
            logger.debug(f"Added audio clip: {clip.name}")
            return obj

        except Exception as e:
            logger.error(f"Error adding audio clip: {e}")
            return None

    def add_transition(self, transition: TransitionProperties) -> bool:
        """Add a transition to the scene.
        
        Args:
            transition: Transition properties
            
        Returns:
            True if successful
        """
        try:
            # Find affected objects
            from_obj = None
            to_obj = None

            for obj in self.objects:
                if obj.get('clip_id') == transition.from_clip:
                    from_obj = obj
                if obj.get('clip_id') == transition.to_clip:
                    to_obj = obj

            if from_obj and to_obj:
                # Add transition data
                from_obj['transition_out'] = {
                    'type': transition.type.value,
                    'duration': transition.duration,
                    'to_clip': transition.to_clip
                }

                to_obj['transition_in'] = {
                    'type': transition.type.value,
                    'duration': transition.duration,
                    'from_clip': transition.from_clip
                }

                logger.debug(f"Added {transition.type.value} transition")
                return True

            return False

        except Exception as e:
            logger.error(f"Error adding transition: {e}")
            return False

    def add_effect(self, effect: EffectProperties) -> bool:
        """Add an effect to the scene.
        
        Args:
            effect: Effect properties
            
        Returns:
            True if successful
        """
        try:
            # Find target clip
            target_obj = None
            for obj in self.objects:
                if obj.get('clip_id') == effect.clip_id:
                    target_obj = obj
                    break

            if target_obj:
                # Add effect data as custom properties
                if 'effects' not in target_obj:
                    target_obj['effects'] = []

                effect_data = {
                    'id': effect.effect_id,
                    'name': effect.name,
                    'type': effect.type.value,
                    'start': effect.start_frame,
                    'duration': effect.duration,
                    'params': effect.params,
                    'keyframes': effect.keyframes
                }

                target_obj['effects'].append(effect_data)
                logger.debug(f"Added effect: {effect.name} to {effect.clip_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error adding effect: {e}")
            return False


class BlenderFileExporter:
    """Exporter for saving Blender scenes to .blend files."""

    def __init__(self, output_path: str, verbose: bool = False):
        """Initialize the exporter.
        
        Args:
            output_path: Path to save the .blend file
            verbose: Enable verbose logging
        """
        self.output_path = Path(output_path)
        self.verbose = verbose

    def export(self) -> bool:
        """Export the current Blender scene to .blend file.
        
        Returns:
            True if successful, False otherwise
        """
        if not BLENDER_AVAILABLE:
            logger.error("Blender (bpy) not available. Cannot export.")
            return False

        try:
            logger.info(f"Exporting to: {self.output_path}")

            # Ensure output directory exists
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save blend file
            bpy.ops.wm.save_as_mainfile(filepath=str(self.output_path))

            logger.info(f"Successfully exported to {self.output_path}")
            return True

        except Exception as e:
            logger.error(f"Error exporting blend file: {e}")
            return False


class DRTToBlendConverter:
    """Main converter class orchestrating the DRT to Blend conversion."""

    def __init__(self, input_file: str, output_file: str, verbose: bool = False, 
                 skip_media: bool = False, fps: float = None):
        """Initialize the converter.
        
        Args:
            input_file: Path to input .drt file
            output_file: Path to output .blend file
            verbose: Enable verbose logging
            skip_media: Skip loading media files
            fps: Override FPS from the DRT file
        """
        self.input_file = input_file
        self.output_file = output_file
        self.verbose = verbose
        self.skip_media = skip_media
        self.fps_override = fps

        self.parser = DRTFileParser(input_file, verbose)
        self.scene_builder = None
        self.exporter = BlenderFileExporter(output_file, verbose)

    def convert(self) -> bool:
        """Execute the conversion process.
        
        Returns:
            True if conversion was successful, False otherwise
        """
        try:
            logger.info("=" * 60)
            logger.info("DRT to Blend Conversion Starting")
            logger.info("=" * 60)

            # Step 1: Parse DRT file
            logger.info("\n[Step 1/4] Parsing DRT file...")
            if not self.parser.parse():
                logger.error("Failed to parse DRT file")
                return False

            # Step 2: Override FPS if specified
            if self.fps_override:
                self.parser.metadata.fps = self.fps_override
                logger.info(f"FPS overridden to {self.fps_override}")

            # Print parsed statistics
            self._print_statistics()

            # Step 3: Build Blender scene
            logger.info("\n[Step 2/4] Building Blender scene...")
            if not BLENDER_AVAILABLE:
                logger.error("Blender Python API (bpy) is not available.")
                logger.error("Please run this script from within Blender or install Blender.")
                return False

            self.scene_builder = BlenderSceneBuilder(self.parser.metadata, self.verbose)
            if not self.scene_builder.build_scene():
                logger.error("Failed to build scene")
                return False

            # Step 4: Add timeline elements
            logger.info("\n[Step 3/4] Adding timeline elements...")
            clips_added = 0
            for clip_id, clip in self.parser.clips.items():
                if self.scene_builder.add_clip(clip):
                    clips_added += 1

            logger.info(f"Added {clips_added}/{len(self.parser.clips)} clips")

            # Add transitions
            transitions_added = 0
            for trans_id, transition in self.parser.transitions.items():
                if self.scene_builder.add_transition(transition):
                    transitions_added += 1

            logger.info(f"Added {transitions_added}/{len(self.parser.transitions)} transitions")

            # Add effects
            effects_added = 0
            for effect_id, effect in self.parser.effects.items():
                if self.scene_builder.add_effect(effect):
                    effects_added += 1

            logger.info(f"Added {effects_added}/{len(self.parser.effects)} effects")

            # Step 5: Export to .blend
            logger.info("\n[Step 4/4] Exporting to .blend file...")
            if not self.exporter.export():
                logger.error("Failed to export blend file")
                return False

            logger.info("\n" + "=" * 60)
            logger.info("Conversion completed successfully!")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"Conversion failed with error: {e}")
            return False

    def _print_statistics(self) -> None:
        """Print conversion statistics."""
        logger.info("\nTimeline Statistics:")
        logger.info(f"  Name: {self.parser.metadata.name}")
        logger.info(f"  Resolution: {self.parser.metadata.resolution_width}x"
                   f"{self.parser.metadata.resolution_height}")
        logger.info(f"  FPS: {self.parser.metadata.fps}")
        logger.info(f"  Duration: {self.parser.metadata.duration_frames} frames "
                   f"({self.parser.metadata.duration_frames / self.parser.metadata.fps:.2f}s)")
        logger.info(f"  Color Space: {self.parser.metadata.color_space}")
        logger.info(f"\nTimeline Elements:")
        logger.info(f"  Clips: {len(self.parser.clips)}")
        logger.info(f"  Transitions: {len(self.parser.transitions)}")
        logger.info(f"  Effects: {len(self.parser.effects)}")
        logger.info(f"  Video Tracks: {len(self.parser.video_tracks)}")
        logger.info(f"  Audio Tracks: {len(self.parser.audio_tracks)}")


def main():
    """Main entry point."""
    # Handle Blender's argument passing
    argv = sys.argv
    # When running from Blender with -b -P script.py -- args
    # Blender adds 'blender.exe' to argv, so we need to find the '--' separator
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        # Remove script name for normal execution
        argv = argv[1:]
    
    parser = argparse.ArgumentParser(
        description='Convert DaVinci Resolve timeline files (.drt) to Blender (.blend)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python drt_to_blend_converter.py timeline.drt output.blend
  python drt_to_blend_converter.py timeline.drt output.blend --verbose
  python drt_to_blend_converter.py timeline.drt output.blend --fps 30
  python drt_to_blend_converter.py timeline.drt output.blend --skip-media --verbose
        """
    )

    parser.add_argument(
        'input_file',
        help='Input DRT file path'
    )
    parser.add_argument(
        'output_file',
        help='Output BLEND file path'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--skip-media',
        action='store_true',
        help='Skip loading media files'
    )
    parser.add_argument(
        '--fps',
        type=float,
        help='Override FPS from the timeline'
    )

    args = parser.parse_args(argv)

    # Create converter
    converter = DRTToBlendConverter(
        input_file=args.input_file,
        output_file=args.output_file,
        verbose=args.verbose,
        skip_media=args.skip_media,
        fps=args.fps
    )

    # Execute conversion
    success = converter.convert()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
