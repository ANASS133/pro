import os
import zipfile


class ZipService:
    def create_zip(self, file_paths, output_path):
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in file_paths:
                    if os.path.exists(file_path):
                        arcname = os.path.basename(file_path)
                        zipf.write(file_path, arcname)
            return output_path
        except Exception as exc:
            raise Exception(f"Error creating ZIP file: {exc}")

    def create_zip_with_folders(self, file_dict, output_path):
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for folder_name, files in file_dict.items():
                    for file_path in files:
                        if os.path.exists(file_path):
                            arcname = os.path.join(folder_name, os.path.basename(file_path))
                            zipf.write(file_path, arcname)
            return output_path
        except Exception as exc:
            raise Exception(f"Error creating ZIP file: {exc}")
