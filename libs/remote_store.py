"""The queue of photos that phones send to the booth.

A guest anywhere at the event opens the remote page, takes a photo with their
own phone and sends it here. The booth then shows what is waiting and prints
whatever a guest picks, so the two ends never share anything but this queue: the
web server appends to it from a request thread, the Kivy UI reads and updates it
from the clock. Every mutation therefore goes through _mutate, which reads,
changes and writes the index under a single lock, the same way StatsStore does.

Photos are re-encoded on the way in rather than stored as received. That is what
bounds a 12 MP phone capture to something a Pi can hold a few hundred of, and it
drops the EXIF block with it, so the GPS coordinates of whoever pressed the
shutter never reach the booth's disk or the gallery.
"""

import json
import logging
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime

import cv2

from libs.file_utils import FileUtils

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy: the queue must stay readable headless.
Logger = logging.getLogger('kivy.photobooth')

# Named by this module: a timestamp for the operator, a random suffix so an id
# cannot be guessed by a phone that was never given it.
REMOTE_ID_PATTERN = re.compile(r'^\d{8}_\d{6}_[0-9a-f]{8}$')
SENDER_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')

# Signatures of the formats a phone camera actually produces. Checked before
# anything is decoded, so a file that is not an image is refused on its size and
# first bytes alone.
IMAGE_SIGNATURES = (
    b'\xff\xd8\xff',      # JPEG
    b'\x89PNG\r\n\x1a\n',  # PNG
)


class RemoteSubmissionError(Exception):
    """A submission that was refused, carrying a message meant for the guest."""


def new_sender_id():
    """Identity a phone keeps in a cookie, so it can see its own sends."""
    return secrets.token_hex(16)


def is_valid_sender_id(sender_id):
    return isinstance(sender_id, str) and bool(SENDER_ID_PATTERN.fullmatch(sender_id))


class RemoteStore:
    """Photos waiting to be printed, and what has already been done with them."""

    STATUS_PENDING = 'pending'
    # Handed to the booth's print flow. The queue stops offering it, but the
    # file stays: the guest who sent it still sees it in their own list.
    STATUS_PRINTED = 'printed'
    STATUS_REJECTED = 'rejected'

    def __init__(self, remote_directory, max_pending=200, max_per_sender=20,
                 max_upload_bytes=12 * 1024 * 1024, max_image_pixels=2400,
                 min_upload_interval=3):
        self.remote_directory = remote_directory
        self.index_file = os.path.join(remote_directory, 'index.json')
        self.max_pending = max(1, int(max_pending))
        self.max_per_sender = max(1, int(max_per_sender))
        self.max_upload_bytes = max(1, int(max_upload_bytes))
        self.max_image_pixels = max(320, int(max_image_pixels))
        self.min_upload_interval = max(0, int(min_upload_interval))
        self._lock = threading.Lock()

        os.makedirs(self.remote_directory, exist_ok=True)

    # --- index, callers must hold the lock --------------------------------

    def _read(self):
        if not os.path.exists(self.index_file):
            return {'entries': []}

        try:
            with open(self.index_file, 'r', encoding='utf-8') as handle:
                index = json.load(handle)
        except (OSError, ValueError) as exc:
            # A truncated index must not take the booth down with it: the photos
            # are still on disk, and a new index is written on the next send.
            Logger.error('RemoteStore: unreadable index, starting from an empty queue: %s', exc)
            return {'entries': []}

        if not isinstance(index, dict) or not isinstance(index.get('entries'), list):
            return {'entries': []}
        return index

    def _write(self, index):
        temp_index_file = f'{self.index_file}.tmp'
        with open(temp_index_file, 'w', encoding='utf-8') as handle:
            json.dump(index, handle, indent=2)
            handle.write('\n')
        os.replace(temp_index_file, self.index_file)

    def _mutate(self, change):
        """Read, change and write the index as one atomic step.

        Unlike the stats file, a failure here is reported: losing a counter is
        invisible, losing a photo a guest just sent is not.
        """
        with self._lock:
            index = self._read()
            result = change(index)
            self._write(index)
            return result

    # --- paths ------------------------------------------------------------

    def is_valid_entry_id(self, entry_id):
        return isinstance(entry_id, str) and bool(REMOTE_ID_PATTERN.fullmatch(entry_id))

    def photo_path(self, entry_id, small=False):
        """Resolve a stored photo, or None when the id is not one this store made."""
        if not self.is_valid_entry_id(entry_id):
            return None

        filename = f'{entry_id}_small.jpg' if small else f'{entry_id}.jpg'
        base_path = os.path.realpath(self.remote_directory)
        requested_path = os.path.realpath(os.path.join(base_path, filename))

        # The id pattern already rules out a separator, but resolve and compare
        # anyway: the directory itself may sit behind a symlink.
        if os.path.dirname(requested_path) != base_path:
            return None

        if not os.path.isfile(requested_path):
            return None

        return requested_path

    # --- reading ----------------------------------------------------------

    def list_entries(self, status=None, sender_id=None, newest_first=True):
        """Entries matching the filters, as copies the caller may keep."""
        with self._lock:
            entries = list(self._read()['entries'])

        if status is not None:
            entries = [entry for entry in entries if entry.get('status') == status]
        if sender_id is not None:
            entries = [entry for entry in entries if entry.get('sender_id') == sender_id]

        entries.sort(key=lambda entry: entry.get('received_at', ''), reverse=newest_first)
        return [dict(entry) for entry in entries]

    def get(self, entry_id):
        with self._lock:
            for entry in self._read()['entries']:
                if entry.get('id') == entry_id:
                    return dict(entry)
        return None

    def count_pending(self):
        with self._lock:
            return sum(
                1 for entry in self._read()['entries']
                if entry.get('status') == self.STATUS_PENDING
            )

    # --- writing ----------------------------------------------------------

    def submit(self, image_bytes, sender_id, source_name=None):
        """Accept one photo from a phone, or refuse it with a reason.

        Raises RemoteSubmissionError with a message the guest is meant to read.
        """
        if not is_valid_sender_id(sender_id):
            raise RemoteSubmissionError('This device is not identified. Reload the page and try again.')

        if not image_bytes:
            raise RemoteSubmissionError('The photo arrived empty. Try again.')

        if len(image_bytes) > self.max_upload_bytes:
            megabytes = self.max_upload_bytes / (1024 * 1024)
            raise RemoteSubmissionError(f'The photo is too large. The limit is {megabytes:.0f} MB.')

        if not image_bytes.startswith(IMAGE_SIGNATURES):
            raise RemoteSubmissionError('Only JPEG and PNG photos are accepted.')

        self._check_quota(sender_id)

        entry_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        # Decoding and re-encoding runs outside the lock: it is the slow part,
        # and holding the queue shut for it would stall the booth's own refresh.
        try:
            self._store_image(entry_id, image_bytes)
        except Exception:
            # A photo written without its thumbnail has no entry pointing at it,
            # so nothing would ever clean it up.
            self._remove_files(entry_id)
            raise

        entry = {
            'id': entry_id,
            'sender_id': sender_id,
            'received_at': datetime.now().isoformat(timespec='seconds'),
            'status': self.STATUS_PENDING,
            'source_name': os.path.basename(source_name or '')[:64] or None,
        }

        def change(index):
            # Checked again now the entry is being inserted: two phones can pass
            # the pre-check at the same time and only one of them may fit.
            pending = sum(1 for item in index['entries'] if item.get('status') == self.STATUS_PENDING)
            if pending >= self.max_pending:
                raise RemoteSubmissionError('The booth already has all the photos it can hold. Try again later.')
            index['entries'].append(entry)
            return dict(entry)

        try:
            stored_entry = self._mutate(change)
        except Exception:
            self._remove_files(entry_id)
            raise

        Logger.info('RemoteStore: accepted photo %s from %s', entry_id, sender_id[:8])
        return stored_entry

    def _check_quota(self, sender_id):
        """Refuse a send before any pixels are decoded.

        Both limits count what is waiting, not what was ever sent: the queue is
        the scarce thing, and a guest who walked to the booth and printed their
        photos has earned the room back.
        """
        now = datetime.now()

        with self._lock:
            entries = self._read()['entries']

        pending = 0
        pending_from_sender = 0
        last_from_sender = None
        for entry in entries:
            is_pending = entry.get('status') == self.STATUS_PENDING
            if is_pending:
                pending += 1
            if entry.get('sender_id') != sender_id:
                continue
            if is_pending:
                pending_from_sender += 1
            received_at = entry.get('received_at')
            if received_at and (last_from_sender is None or received_at > last_from_sender):
                last_from_sender = received_at

        if pending >= self.max_pending:
            raise RemoteSubmissionError('The booth already has all the photos it can hold. Try again later.')

        if pending_from_sender >= self.max_per_sender:
            raise RemoteSubmissionError(
                f'You have {self.max_per_sender} photos waiting. Print some at the booth to send more.'
            )

        if self.min_upload_interval and last_from_sender:
            try:
                elapsed = (now - datetime.fromisoformat(last_from_sender)).total_seconds()
            except ValueError:
                elapsed = self.min_upload_interval
            if 0 <= elapsed < self.min_upload_interval:
                raise RemoteSubmissionError('Sending too fast. Wait a moment and try again.')

    def _store_image(self, entry_id, image_bytes):
        """Write the photo and its thumbnail, upright and re-encoded.

        The bytes go through a temporary file rather than cv2.imdecode because
        only cv2.imread applies the EXIF orientation tag. Decoding the buffer
        directly is what leaves a phone photo lying on its side, which is
        exactly how it would then be printed.
        """
        handle, temp_path = tempfile.mkstemp(prefix='.upload_', suffix='.img', dir=self.remote_directory)
        try:
            with os.fdopen(handle, 'wb') as temp_file:
                temp_file.write(image_bytes)

            image = cv2.imread(temp_path, cv2.IMREAD_COLOR)
        finally:
            FileUtils.remove_file(temp_path)

        if image is None:
            raise RemoteSubmissionError('This file is not a photo the booth can read.')

        image = FileUtils.resize(image, max_height=self.max_image_pixels, max_width=self.max_image_pixels)
        photo_path = os.path.join(self.remote_directory, f'{entry_id}.jpg')
        FileUtils.write_image(photo_path, image)
        FileUtils.write_image(FileUtils.get_small_path(photo_path), FileUtils.resize(image, 480, 480))

    def set_status(self, entry_id, status):
        """Move an entry to another status; returns the updated copy or None."""
        if status not in (self.STATUS_PENDING, self.STATUS_PRINTED, self.STATUS_REJECTED):
            raise ValueError(f'Unknown remote photo status: {status}')

        def change(index):
            for entry in index['entries']:
                if entry.get('id') == entry_id:
                    entry['status'] = status
                    return dict(entry)
            return None

        updated_entry = self._mutate(change)
        if updated_entry is not None:
            Logger.info('RemoteStore: photo %s is now %s', entry_id, status)
        return updated_entry

    def delete(self, entry_id, sender_id=None):
        """Remove an entry and its files. A sender_id restricts it to its owner."""
        def change(index):
            for position, entry in enumerate(index['entries']):
                if entry.get('id') != entry_id:
                    continue
                if sender_id is not None and entry.get('sender_id') != sender_id:
                    return False
                del index['entries'][position]
                return True
            return False

        if not self._mutate(change):
            return False

        self._remove_files(entry_id)
        Logger.info('RemoteStore: deleted photo %s', entry_id)
        return True

    def purge(self):
        """Drop every remote photo; returns how many entries were removed."""
        def change(index):
            entry_ids = [entry.get('id') for entry in index['entries']]
            index['entries'] = []
            return entry_ids

        entry_ids = self._mutate(change)
        for entry_id in entry_ids:
            self._remove_files(entry_id)

        Logger.info('RemoteStore: purged remote photos removed=%s', len(entry_ids))
        return len(entry_ids)

    def _remove_files(self, entry_id):
        if not self.is_valid_entry_id(entry_id):
            return

        photo_path = os.path.join(self.remote_directory, f'{entry_id}.jpg')
        for path in (photo_path, FileUtils.get_small_path(photo_path)):
            try:
                FileUtils.remove_file(path)
            except OSError as exc:
                Logger.warning('RemoteStore: could not remove %s: %s', path, exc)
