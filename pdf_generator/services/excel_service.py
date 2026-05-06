import os
from datetime import datetime

import pandas as pd


class ExcelService:
    def __init__(self):
        self.supported_formats = ['.xlsx', '.xls', '.csv']

    def parse_excel(self, filepath):
        try:
            df = self._read_dataframe(filepath)
            df.columns = [self._clean_column_name(col) for col in df.columns]
            df = df.fillna('')

            columns = list(df.columns)
            if not columns:
                raise Exception('No columns found in file')

            rows = []
            for _, row in df.iterrows():
                row_dict = {}
                for col in columns:
                    value = row[col]
                    if pd.isna(value):
                        row_dict[col] = ''
                    elif isinstance(value, (datetime, pd.Timestamp)):
                        row_dict[col] = value.strftime('%d.%m.%Y')
                    else:
                        row_dict[col] = str(value)
                rows.append(row_dict)

            if not rows:
                raise Exception('No data rows found in file')

            return {
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
                'column_count': len(columns),
            }
        except Exception as exc:
            raise Exception(f'Error parsing data file: {exc}')

    def _read_dataframe(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        if ext in ('.xlsx', '.xls'):
            return pd.read_excel(filepath, dtype=str)
        if ext == '.csv':
            return self._read_csv_with_autodetect(filepath)
        raise Exception(f'Unsupported file format: {ext}')

    def _read_csv_with_autodetect(self, filepath):
        encodings = ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1')
        delimiters = (',', ';', '\t')
        last_error = None
        best_candidate = None
        best_score = (-1, -1)

        for encoding in encodings:
            for delimiter in delimiters:
                try:
                    df = pd.read_csv(
                        filepath,
                        dtype=str,
                        encoding=encoding,
                        sep=delimiter,
                    )
                    if len(df.columns) > 1:
                        return df
                    if len(df.columns) > 0:
                        score = (len(df.columns), len(df.index))
                        if score > best_score:
                            best_score = score
                            best_candidate = df
                except Exception as exc:
                    last_error = exc

        if best_candidate is not None:
            return best_candidate

        raise Exception(f'Unable to parse CSV with supported encodings/delimiters: {last_error}')

    def _clean_column_name(self, name):
        if not isinstance(name, str):
            name = str(name)
        name = name.strip().replace(' ', '')
        return name

    def validate_excel_structure(self, filepath, required_columns=None):
        df = self._read_dataframe(filepath).head(0)
        actual_columns = list(df.columns)
        if required_columns:
            missing_columns = [col for col in required_columns if col not in actual_columns]
            if missing_columns:
                return False, f'Missing required columns: {missing_columns}'
        return True, 'Excel structure is valid'

    def get_column_preview(self, filepath, column_name, num_rows=5):
        df = self._read_dataframe(filepath).head(num_rows)
        if column_name in df.columns:
            return df[column_name].tolist()
        return []

    def detect_column_types(self, filepath):
        df = self._read_dataframe(filepath)
        column_types = {}
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                column_types[col] = 'date'
            elif pd.api.types.is_numeric_dtype(df[col]):
                column_types[col] = 'number'
            else:
                column_types[col] = 'text'
        return column_types
