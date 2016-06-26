from abc import abstractproperty, abstractmethod
import os
import re
import tifffile
from collections import defaultdict
import numpy as np


whitespace_regex = re.compile('[\s]+')
special_chars_regex = re.compile('[\W]+')
name_regex = re.compile('Pos_(\d+)_(\d+)\D')


def sanitize_name(name):
    return special_chars_regex.sub('', whitespace_regex.sub('_', name))


class BaseTifStack(object):
    def __init__(self, filenames, adjustments):
        self._filenames = filenames
        self._adjustments = adjustments
        self._axes = {}

    @abstractproperty
    def axes(self):
        raise NotImplementedError

    @abstractmethod
    def __iter__(self):
        raise NotImplementedError


class TifsPerFieldOfView(BaseTifStack):
    # What we've had for a while now, produced by microscope 2
    @property
    def axes(self):
        if not self._axes:
            tif_axes = {}
            best_first = 0
            best_second = 0
            for file_path in self._filenames:
                filename = os.path.split(file_path)[1]
                axis_positions = name_regex.search(filename)
                first = int(axis_positions.group(1))
                second = int(axis_positions.group(2))
                best_first = max(first, best_first)
                best_second = max(second, best_second)
                tif_axes[file_path] = (first, second)
            if best_second > best_first:
                # the second thing is the major axis, so we need to invert them
                self._axes = {file_path: (second, first) for file_path, (first, second) in tif_axes.items()}
            # no need to invert, just return the values we already have
            else:
                self._axes = tif_axes
        return self._axes

    def __iter__(self):
        for file_path in self._filenames:
            major_axis_position, minor_axis_position = self.axes[file_path]
            dataset_name = '(Major, minor) = ({}, {})'.format(major_axis_position, minor_axis_position)

            with tifffile.TiffFile(file_path) as tif:
                summary = tif.micromanager_metadata['summary']

                # Find channel names and assert unique
                channel_names = [sanitize_name(name) for name in summary['ChNames']]
                assert summary['Channels'] == len(channel_names) == len(set(channel_names)), channel_names

                # channel_idxs map tif pages to channels
                channels = [channel_names[i] for i in tif.micromanager_metadata['index_map']['channel']]

                # Setup defaultdict
                height, width = summary['Height'], summary['Width']
                summed_images = defaultdict(lambda *x: np.zeros((height, width), dtype=np.int))

                # Add images
                for channel, page in zip(channels, tif.pages):
                    image = page.asarray()
                    for adjustment in self._adjustments:
                        image = adjustment(image)
                    summed_images[channel] += image
                yield TIFSingleFieldOfView(summed_images, dataset_name)


class TifsPerConcentration(BaseTifStack):
    # the new format from microscope 4
    pass


class TIFSingleFieldOfView(object):
    """
    Contains images and metadata for a single field of view at a single concentration.

    """
    def __init__(self, summed_images, dataset_name):
        self._summed_images = summed_images
        self._dataset_name = dataset_name

    @property
    def dataset_name(self):
        return self._dataset_name

    def __repr__(self):
        return "<TIFSingleFieldOfView %s>" % self._dataset_name

    def __iter__(self):
        for channel, image in self._summed_images.items():
            yield channel, image