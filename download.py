#!/usr/bin/python3

import datetime
import os
import re
import sys
import shutil
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

class Downloader:

    def __init__(self, url, outdir):
        # Allow to initialize without a preferred outdir.
        # So, pick a temporary one.
        self.tmp_outdir = None
        if not outdir:
            self.tmp_outdir = tempfile.TemporaryDirectory()
            outdir = self.tmp_outdir.name

        m = re.match(r'^.*/playback/presentation/2\.0/playback\.html\?meetingId=(\S+)$', url)
        if m is not None:
            id = m.group(1)
        else:
            m = re.match(r'^.*/playback/presentation/2\.3/(\S+)$', url)
            if m is not None:
                id = m.group(1)
            else:
                raise ValueError(f"Does not look like a BBB playback URL: {url}")

        id = m.group(1)
        self.base_url = urllib.parse.urljoin(url, f"/presentation/{id}/")
        self.outdir = outdir

    # Download a specific file.
    # Example: if path is 'asd.xml', then this URL is fetched:
    # https://bbb.example.com/presentation/token/asd.xml
    def _get(self, path):
        url = urllib.parse.urljoin(self.base_url, path)
        outpath = os.path.join(self.outdir, path)
        os.makedirs(os.path.dirname(outpath), exist_ok=True)

        print(f"Downloading {url}", end="")
        with open(outpath, 'wb') as fp:
            buf = bytearray(64 * 1024)
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'bbb-video-downloader/1.0')
            resp = urllib.request.urlopen(req)
            content_length = resp.headers['Content-Length']
            if content_length is not None:
                content_length = int(content_length)
                print(f" ({content_length} bytes)...")
            else:
                print("...")
            while True:
                with resp:
                    n = resp.readinto(buf)
                    while n > 0:
                        fp.write(buf[:n])
                        n = resp.readinto(buf)
                current = fp.seek(0, os.SEEK_CUR)
                if content_length is None or current >= content_length:
                    break
                print("continuing...")
                req = urllib.request.Request(url)
                req.add_header('User-Agent', 'bbb-video-downloader/1.0')
                req.add_header('Range', f'bytes={current}-')
                resp = urllib.request.urlopen(req)
        return outpath

    def download(self):
        metadata_str = self._get('metadata.xml')
        metadata_tree = ET.parse(metadata_str)

        # Parse the metadata.xml to get a formatted start date.
        start_time_formatted = "YYYY-MM-DD-HH-II-SS"
        start_time_tag = metadata_tree.find('start_time')
        if start_time_tag is not None: #FuckPython.... 'if var:' does not work
            start_time_ms = int(metadata_tree.find('start_time').text)
            start_time_s = start_time_ms / 1000.0
            start_time = datetime.datetime.fromtimestamp(start_time_s)
            start_time_formatted = start_time.strftime('%Y-%m-%d-%H-%M-%S')

        # Parse the metadata.xml to find the meeting name and generate a slug.
        meeting_name_slug = "video-name-slug"
        meeting_element = metadata_tree.find('meeting')
        if meeting_element is not None: #FuckPython.... 'if var:' does not work
            meeting_name = meeting_element.get('name')
            if meeting_name is not None: #FuckPython.... 'if var:' does not work
                meeting_name_slug = create_slug(meeting_name)

        shapes = self._get('shapes.svg')
        doc = ET.parse(shapes)
        for imgurl in {img.get('{http://www.w3.org/1999/xlink}href')
                       for img in doc.iterfind('.//{http://www.w3.org/2000/svg}image')}:
            self._get(imgurl)
        
        components = ['panzooms.xml',
                      'cursor.xml',
                      'deskshare.xml',
                      'presentation_text.json',
                      'captions.json',
                      'slides_new.xml',
                      'video/webcams.webm',
                      'video/webcams.mp4',
                      'deskshare/deskshare.webm',
                      'deskshare/deskshare.mp4',
        ]

        for item in components:
            try:
                self._get(item)
            except Exception:
                f"Component {item} not available in presentation"

        # Move the temporary directory to the final location.
        definitive_directory = self.outdir
        if self.tmp_outdir is not None: #FuckPython: 'if var:' does not work
            definitive_directory_base = "materials/"
            os.makedirs(definitive_directory_base, exist_ok=True)
            definitive_directory = definitive_directory_base + start_time_formatted + "-" + meeting_name_slug
            shutil.move(self.tmp_outdir.name, definitive_directory)
            self.tmp_outdir = None # attempt to avoid tmp dir cleanup

        print("")
        print("SUCCESS! Everything was downloaded here:")
        print("  " + definitive_directory)
        print("")
        print("SUGGESTION: Now run this command to create the Pitivi file:")
        print("  ./make-xges.py {} {}.xges".format(definitive_directory, definitive_directory))


# Function to create a slug from a string
def create_slug(name):
    if name:
        # Convert to lowercase
        name = name.lower()
        # Replace spaces with hyphens
        name = re.sub(r'\s+', '-', name)
        # Remove special characters (keeping only alphanumeric and hyphens)
        name = re.sub(r'[^a-z0-9-]', '', name)
        return name
    return None

def main(argv):
    if len(argv) < 2 or len(argv) > 3:
        sys.stderr.write('usage: {} PRESENTATION-URL [OUTPUT-DIR]\n'.format(argv[0]))
        return 1

    url = argv[1]
    dirname = None
    if len(argv) > 2:
        dirname = argv[2]

    d = Downloader(url, dirname)
    d.download()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
