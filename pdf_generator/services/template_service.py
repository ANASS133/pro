import re
from datetime import date


class TemplateService:
    def __init__(self):
        self.placeholder_pattern = re.compile(r"{{\s*([^{}]+?)\s*}}")
        self.builtin_placeholders = {"heutigenDatum", "heutigeDatum", "heutigentag", "todayDate"}
        self.windows_reserved_filenames = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }

    def _builtin_values(self):
        today_str = date.today().strftime("%d.%m.%Y")
        return {
            "heutigenDatum": today_str,
            "heutigeDatum": today_str,
            "heutigentag": today_str,
            "todayDate": today_str,
        }

    def _normalize_key(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _build_row_lookup(self, row_data, columns):
        exact_lookup = {}
        lower_lookup = {}
        normalized_lookup = {}
        for col in columns or []:
            col_name = str(col or "").strip()
            if not col_name:
                continue
            value = row_data.get(col, row_data.get(col_name, ""))
            exact_lookup[col_name] = value
            lower_lookup[col_name.lower()] = value
            normalized_lookup[self._normalize_key(col_name)] = value

        for raw_key, raw_value in (row_data or {}).items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            exact_lookup.setdefault(key, raw_value)
            lower_lookup.setdefault(key.lower(), raw_value)
            normalized_lookup.setdefault(self._normalize_key(key), raw_value)

        return exact_lookup, lower_lookup, normalized_lookup

    def _resolve_placeholder_value(
        self, key, builtin_values, exact_lookup, lower_lookup, normalized_lookup
    ):
        if key in builtin_values:
            return builtin_values[key]
        if key in exact_lookup:
            return exact_lookup[key]
        lowered = key.lower()
        if lowered in lower_lookup:
            return lower_lookup[lowered]
        normalized = self._normalize_key(key)
        if normalized in normalized_lookup:
            return normalized_lookup[normalized]
        return ""

    def replace_placeholders(self, template, row_data, columns):
        if not template:
            return ""

        builtin_values = self._builtin_values()
        exact_lookup, lower_lookup, normalized_lookup = self._build_row_lookup(
            row_data or {}, columns or []
        )

        def _replace(match):
            key = str(match.group(1) or "").strip()
            value = self._resolve_placeholder_value(
                key,
                builtin_values,
                exact_lookup,
                lower_lookup,
                normalized_lookup,
            )
            if value is None:
                return ""
            return str(value)

        return self.placeholder_pattern.sub(_replace, template)

    def validate_placeholders(self, template, available_columns):
        if not template:
            return []
        placeholders = list(set(self.placeholder_pattern.findall(template)))
        exact_columns = {str(col or "").strip() for col in available_columns or []}
        lower_columns = {col.lower() for col in exact_columns}
        normalized_columns = {self._normalize_key(col) for col in exact_columns}
        missing = []
        for placeholder in placeholders:
            key = str(placeholder or "").strip()
            if not key or key in self.builtin_placeholders:
                continue
            if key in exact_columns:
                continue
            if key.lower() in lower_columns:
                continue
            if self._normalize_key(key) in normalized_columns:
                continue
            missing.append(key)
        return missing

    def extract_placeholders(self, template):
        if not template:
            return []
        placeholders = self.placeholder_pattern.findall(template)
        return list(set(placeholders))

    def _sanitize_filename_stem(self, value, fallback):
        fallback_name = str(fallback or "").strip() or "document"
        candidate = str(value or "").strip()
        candidate = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", candidate)
        candidate = re.sub(r"-{2,}", "-", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip().rstrip(". ")

        if not candidate:
            candidate = fallback_name
        if candidate.upper() in self.windows_reserved_filenames:
            candidate = f"{candidate}_"
        if len(candidate) > 180:
            candidate = candidate[:180].rstrip(". ")
        return candidate or fallback_name

    def generate_filename(self, format_string, row_data, columns, index):
        rendered = self.replace_placeholders(format_string, row_data, columns)
        filename = self._sanitize_filename_stem(rendered, f"document_{index + 1}")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        return filename

    def create_default_template(self):
        return ""
