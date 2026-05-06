import hashlib
import os
from datetime import datetime, timedelta


class FileUtils:
    @staticmethod
    def safe_filename(filename):
        filename = filename.replace(' ', '_')
        filename = ''.join(c for c in filename if c.isalnum() or c in '._-')
        if not filename:
            filename = 'document'
        return filename

    @staticmethod
    def get_file_size(filepath):
        size_bytes = os.path.getsize(filepath)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f} TB"

    @staticmethod
    def cleanup_old_files(directory, hours=24):
        now = datetime.now()
        cutoff = now - timedelta(hours=hours)

        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_modified < cutoff:
                    os.remove(filepath)

    @staticmethod
    def get_file_hash(filepath):
        hash_md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def ensure_directory(directory):
        os.makedirs(directory, exist_ok=True)
        return directory
