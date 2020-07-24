#!/usr/bin/python3

import argparse
import os
import sys
import xml.etree.ElementTree as ET

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GES', '1.0')
from gi.repository import GLib, GObject, Gst, GES


def file_to_uri(path):
    path = os.path.realpath(path)
    return 'file://' + path


class Presentation:

    def __init__(self, opts):
        self.opts = opts
        self.cam_width = round(opts.width * opts.webcam_size / 100)
        self.slides_width = opts.width - self.cam_width
        self.start_time = round(opts.start * Gst.SECOND)
        self.end_time = None
        if opts.end is not None:
            self.end_time = round(opts.end * Gst.SECOND)

        self.timeline = GES.Timeline.new_audio_video()

        # Get the timeline's two tracks
        self.video_track, self.audio_track = self.timeline.get_tracks()
        if self.video_track.type == GES.TrackType.AUDIO:
            self.video_track, self.audio_track = self.audio_track, self.video_track
        self.project = self.timeline.get_asset()
        self._assets = {}

        # Construct the presentation
        self.set_track_caps()
        self.add_webcams()
        self.add_slides()
        self.add_deskshare()
        self.add_backdrop()

    def _add_layer(self, name):
        layer = self.timeline.append_layer()
        layer.register_meta_string(GES.MetaFlag.READWRITE, 'video::name', name)
        return layer

    def _get_asset(self, path):
        asset = self._assets.get(path)
        if asset is None:
            asset = GES.UriClipAsset.request_sync(file_to_uri(path))
            self.project.add_asset(asset)
            self._assets[path] = asset
        return asset

    def _get_dimensions(self, asset):
        info = asset.get_info()
        video_info = info.get_video_streams()[0]
        return (video_info.get_width(), video_info.get_height())

    def _add_clip(self, layer, asset, start, inpoint, duration,
                  posx, posy, width, height):
        if self.end_time is not None:
            # Skip clips entirely after the end point
            if start > self.end_time:
                return
            # Truncate clips that go past the end point
            duration = min(duration, self.end_time - start)

        # Skip clips entirely before the start point
        if start + duration < self.start_time:
            return
        # Rewrite start, inpoint, and duration to account for time skip
        start -= self.start_time
        if start < 0:
            duration += start
            if not asset.is_image():
                inpoint += -start
            start = 0

        clip = layer.add_asset(asset, start, inpoint, duration,
                               GES.TrackType.UNKNOWN)
        for element in clip.find_track_elements(
                self.video_track, GES.TrackType.VIDEO, GObject.TYPE_NONE):
            element.set_child_property("posx", posx)
            element.set_child_property("posy", posy)
            element.set_child_property("width", width)
            element.set_child_property("height", height)

    def set_track_caps(self):
        # Set frame rate and audio rate based on webcam capture
        asset = self._get_asset(
            os.path.join(self.opts.basedir, 'video/webcams.webm'))
        info = asset.get_info()

        video_info = info.get_video_streams()[0]
        self.video_track.props.restriction_caps = Gst.Caps.from_string(
            'video/x-raw(ANY), width=(int){}, height=(int){}, '
            'framerate=(fraction){}/{}'.format(
                self.opts.width, self.opts.height,
                video_info.get_framerate_num(),
                video_info.get_framerate_denom()))

        audio_info = info.get_audio_streams()[0]
        self.audio_track.props.restriction_caps = Gst.Caps.from_string(
            'audio/x-raw(ANY), rate=(int){}, channels=(int){}'.format(
                audio_info.get_sample_rate(), audio_info.get_channels()))

    def add_webcams(self):
        layer = self._add_layer('Camera')
        asset = self._get_asset(
            os.path.join(self.opts.basedir, 'video/webcams.webm'))
        orig_width, orig_height = self._get_dimensions(asset)
        width = self.cam_width
        height = round(width / orig_width * orig_height)

        self._add_clip(layer, asset, 0, 0, asset.props.duration,
                       self.opts.width - width, self.opts.height - height,
                       width, height)

    def add_slides(self):
        layer = self._add_layer('Slides')
        doc = ET.parse(os.path.join(self.opts.basedir, 'shapes.svg'))
        for img in doc.iterfind('./{http://www.w3.org/2000/svg}image'):
            path = img.get('{http://www.w3.org/1999/xlink}href')
            # If this is a "deskshare" slide, don't show anything
            if path.endswith('/deskshare.png'):
                continue

            start = round(float(img.get('in')) * Gst.SECOND)
            end = round(float(img.get('out')) * Gst.SECOND)

            asset = self._get_asset(os.path.join(self.opts.basedir, path))
            orig_width, orig_height = self._get_dimensions(asset)
            height = round(self.slides_width / orig_width * orig_height)
            self._add_clip(layer, asset, start, 0, end - start,
                           0, 0, self.slides_width, height)

    def add_deskshare(self):
        layer = self._add_layer('Deskshare')
        asset = self._get_asset(
            os.path.join(self.opts.basedir, 'deskshare/deskshare.webm'))
        orig_width, orig_height = self._get_dimensions(asset)
        height = round(self.slides_width / orig_width * orig_height)
        duration = asset.props.duration
        doc = ET.parse(os.path.join(self.opts.basedir, 'deskshare.xml'))
        for event in doc.iterfind('./event'):
            start = round(float(event.get('start_timestamp')) * Gst.SECOND)
            end = round(float(event.get('stop_timestamp')) * Gst.SECOND)
            # Trim event to duration of video
            if start > duration: continue
            end = min(end, duration)

            self._add_clip(layer, asset, start, start, end - start,
                           0, 0, self.slides_width, height)

    def add_backdrop(self):
        if not self.opts.backdrop:
            return
        # Get duration of webcam footage
        webcams_asset = self._get_asset(
            os.path.join(self.opts.basedir, 'video/webcams.webm'))
        duration = webcams_asset.props.duration

        layer = self._add_layer('Backdrop')
        asset = self._get_asset(self.opts.backdrop)
        self._add_clip(layer, asset, 0, 0, duration,
                       0, 0, self.opts.width, self.opts.height)

    def save(self):
        self.timeline.commit_sync()
        self.timeline.save_to_uri(file_to_uri(self.opts.project), None, True)


def main(argv):
    parser = argparse.ArgumentParser(description='convert a BigBlueButton presentation into a GES project')
    parser.add_argument('--start', metavar='SECONDS', type=float, default=0,
                        help='Seconds to skip from the start of the recording')
    parser.add_argument('--end', metavar='SECONDS', type=float, default=None,
                        help='End point in the recording')
    parser.add_argument('--width', metavar='WIDTH', type=int, default=1920,
                        help='Video width')
    parser.add_argument('--height', metavar='HEIGHT', type=int, default=1080,
                        help='Video height')
    parser.add_argument('--webcam-size', metavar='PERCENT', type=int,
                        default=25, choices=range(100),
                        help='Amount of screen to reserve for camera')
    parser.add_argument('--backdrop', metavar='FILE', type=str, default=None,
                        help='Backdrop image for the project')
    parser.add_argument('basedir', metavar='PRESENTATION-DIR', type=str,
                        help='directory containing BBB presentation assets')
    parser.add_argument('project', metavar='OUTPUT', type=str,
                        help='output filename for GES project')
    opts = parser.parse_args(argv[1:])
    Gst.init(None)
    GES.init()
    p = Presentation(opts)
    p.save()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
