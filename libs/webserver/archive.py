"""Streaming a ZIP without holding it in memory."""


class ArchiveStream:
    """Write target for ZipFile that hands each chunk straight to the response.

    Only tell() is provided, no seek: zipfile then writes a streamable archive
    with data descriptors instead of rewinding to patch headers. After an
    evening of photos the finished archive does not fit in a Pi's memory, so it
    is never assembled in one piece.
    """

    def __init__(self):
        self._chunks = []
        self._offset = 0

    def write(self, data):
        self._chunks.append(data)
        self._offset += len(data)
        return len(data)

    def tell(self):
        return self._offset

    def flush(self):
        pass

    def drain(self):
        chunks, self._chunks = self._chunks, []
        return b''.join(chunks)
