"""Object storage abstraction — StorageBackend interface and local filesystem.

Provides the ``StorageBackend`` protocol with ``put``/``get``/``delete``
methods, and a ``LocalFileSystemBackend`` implementation that writes files
to ``config.STORAGE_LOCAL_PATH``. The factory function ``get_storage()``
selects the backend based on the ``STORAGE_BACKEND`` env var.
"""

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from app.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)

PHOTO_SUBDIR = "sightings"
CONTENT_TYPE_JPEG = "image/jpeg"
FILE_EXTENSION = ".jpg"


class StorageBackend(ABC):
    """Abstract base class for object storage backends.

    Subclasses must implement ``put``, ``get``, and ``delete`` to provide
    a uniform interface for photo storage regardless of the underlying
    storage mechanism (local filesystem, S3, MinIO, etc.).
    """

    @abstractmethod
    def put(self, data: bytes, content_type: str = CONTENT_TYPE_JPEG) -> str:
        """Store a binary blob and return its URL.

        Args:
            data: Raw bytes to store.
            content_type: MIME type of the stored object.

        Returns:
            str: A URL or path that can be used to retrieve the object.
        """
        ...

    @abstractmethod
    def get(self, url: str) -> bytes:
        """Retrieve a previously stored binary blob.

        Args:
            url: The URL or path returned by ``put``.

        Returns:
            bytes: The stored binary content.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        ...

    @abstractmethod
    def delete(self, url: str) -> None:
        """Delete a previously stored binary blob.

        Args:
            url: The URL or path returned by ``put``.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        ...


class LocalFileSystemBackend(StorageBackend):
    """Storage backend that writes files to the local filesystem.

    Files are stored under ``STORAGE_LOCAL_PATH/sightings/`` with
    UUID-based filenames to avoid collisions.
    """

    def __init__(self, base_path: str) -> None:
        """Initialise the local filesystem backend.

        Args:
            base_path: Root directory for file storage.
        """
        self._base_path = Path(base_path)
        self._sightings_dir = self._base_path / PHOTO_SUBDIR
        self._sightings_dir.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, content_type: str = CONTENT_TYPE_JPEG) -> str:
        """Store a binary blob as a file on the local filesystem.

        Args:
            data: Raw bytes to store.
            content_type: MIME type (unused for local FS; stored for interface
                compliance).

        Returns:
            str: Relative path to the stored file.
        """
        filename = f"{uuid.uuid4().hex}{FILE_EXTENSION}"
        file_path = self._sightings_dir / filename
        file_path.write_bytes(data)

        relative_path = f"/{PHOTO_SUBDIR}/{filename}"
        logger.debug(
            "photo_stored_local",
            path=relative_path,
            size=len(data),
        )
        return relative_path

    def get(self, url: str) -> bytes:
        """Retrieve a file from the local filesystem.

        Args:
            url: Relative path returned by ``put``.

        Returns:
            bytes: File contents.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        file_path = self._resolve_path(url)
        if not file_path.exists():
            raise FileNotFoundError(f"Photo not found: {url}")
        return file_path.read_bytes()

    def delete(self, url: str) -> None:
        """Delete a file from the local filesystem.

        Args:
            url: Relative path returned by ``put``.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        file_path = self._resolve_path(url)
        if not file_path.exists():
            raise FileNotFoundError(f"Photo not found: {url}")
        file_path.unlink()
        logger.debug("photo_deleted_local", path=url)

    def _resolve_path(self, url: str) -> Path:
        """Resolve a relative URL to an absolute filesystem path.

        Args:
            url: Relative path (e.g. ``/sightings/abc.jpg``).

        Returns:
            Path: Absolute path under the base storage directory.
        """
        relative = url.lstrip("/")
        return self._base_path / relative


def get_storage() -> StorageBackend:
    """Factory function that returns the configured storage backend.

    Reads the ``STORAGE_BACKEND`` env var to select between local
    filesystem and future S3/MinIO backends.

    Returns:
        StorageBackend: An initialised storage backend instance.
    """
    backend_type = settings.STORAGE_BACKEND.lower()
    if backend_type == "local":
        return LocalFileSystemBackend(settings.STORAGE_LOCAL_PATH)
    raise ValueError(f"Unsupported storage backend: {backend_type}")
