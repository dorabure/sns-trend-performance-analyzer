import csv
from io import StringIO
from os import PathLike
from pathlib import Path

from app.dto.normalized import NormalizedRecord, ProviderResult, SourceType, ValidationError
from app.normalizers.common import Normalizer, is_sensitive_field
from app.providers.base import CsvDatasetType, DataProvider, ProviderFileError, RowValidationError
from app.providers.csv_schema import SCHEMAS


def fatal(code: str, message: str, row_number: int | None = None, field: str = "file") -> ProviderFileError:
    return ProviderFileError(ValidationError(row_number, field, code, message))


class CSVProvider(DataProvider):
    def __init__(self, normalizer: Normalizer | None = None):
        self.normalizer = normalizer if normalizer is not None else Normalizer()

    def read(self, path: str | PathLike[str], dataset_type: CsvDatasetType) -> ProviderResult[NormalizedRecord]:
        dataset_type = CsvDatasetType(dataset_type)
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
                return self._read(source, dataset_type)
        except FileNotFoundError:
            raise fatal("FILE_NOT_FOUND", "CSV file was not found") from None
        except UnicodeDecodeError:
            raise fatal("INVALID_ENCODING", "CSV must use UTF-8") from None
        except OSError:
            raise fatal("FILE_UNREADABLE", "CSV file cannot be read") from None

    def read_text(self, content: str, dataset_type: CsvDatasetType) -> ProviderResult[NormalizedRecord]:
        """Convenience adapter for already-decoded UTF-8 input; does not guess dataset."""
        return self._read(StringIO(content.removeprefix("\ufeff"), newline=""), CsvDatasetType(dataset_type))

    def _read(self, source, dataset_type: CsvDatasetType) -> ProviderResult[NormalizedRecord]:
        reader = csv.reader(source, strict=True)
        records: list[NormalizedRecord] = []
        errors: list[ValidationError] = []
        total_rows = 0
        try:
            original = next(reader, None)
            if original is None or not original or not any(h.strip() for h in original):
                raise fatal("MISSING_HEADER", "CSV header is required", 1, "header")
            headers = [h.strip() for h in original]
            if "" in headers:
                raise fatal("EMPTY_HEADER", "CSV header names cannot be empty", 1, "header")
            if len(set(headers)) != len(headers):
                raise fatal("DUPLICATE_HEADER", "CSV header names must be unique", 1, "header")
            if any(is_sensitive_field(h) for h in headers):
                raise fatal("SENSITIVE_HEADER", "Credential columns are not permitted", 1, "header")
            missing = set(SCHEMAS[dataset_type].headers) - set(headers)
            if missing:
                raise fatal("MISSING_HEADER", "Missing required headers: " + ", ".join(sorted(missing)), 1, "header")
            while True:
                row_number = reader.line_num + 1
                cells = next(reader, None)
                if cells is None:
                    break
                # Ignore physically blank lines; rows of empty cells still undergo validation.
                if not cells:
                    continue
                if len(cells) != len(headers):
                    raise fatal("MALFORMED_CSV", "CSV row width differs from header", row_number)
                total_rows += 1
                raw = dict(zip(headers, cells, strict=True))
                canonical = dict(raw)
                canonical["platform_post_id"] = raw.get("post_id", "")
                canonical["recorded_date"] = raw.get("date", "")
                try:
                    if dataset_type == CsvDatasetType.ACCOUNT_DAILY:
                        record = self.normalizer.normalize_account_metric(canonical, row_number, raw)
                    elif dataset_type == CsvDatasetType.TREND_POSTS:
                        record = self.normalizer.normalize_trend(canonical, row_number, raw)
                    else:
                        source_type = SourceType.OWN if dataset_type == CsvDatasetType.OWN_POSTS else SourceType.COMPETITOR
                        record = self.normalizer.normalize_post(canonical, source_type, row_number, raw,
                                                               include_followers=dataset_type == CsvDatasetType.COMPETITOR_POSTS)
                    records.append(record)
                except RowValidationError as error:
                    aliases = {"platform_post_id": "post_id", "recorded_date": "date"}
                    errors.extend(ValidationError(e.row_number, aliases.get(e.field, e.field), e.code, e.message) for e in error.errors)
        except csv.Error:
            raise fatal("MALFORMED_CSV", "CSV structure or field size is invalid", reader.line_num) from None
        return ProviderResult(records, errors, total_rows)
