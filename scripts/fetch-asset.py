#!/usr/bin/env python3
"""Search StyleKit's public asset catalogue or fetch one exact asset."""

import argparse
import base64
import hashlib
import io
import ipaddress
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit


BASE = "https://www.stylekit.top/api/assets"
CONTRACT = "stylekit-assets-v1"
AVAILABILITY = {"bundled", "remote", "external", "restricted"}
CONTENT_LEVELS = {"source", "metadata", "remote", "restricted"}
MAX_TEMPLATE_BYTES = 50 * 1024 * 1024
MAX_PROJECT_BYTES = 100 * 1024 * 1024
MAX_PROJECT_FILES = 500
BINARY_ENCODING = "UTF-8 text; paths listed in binaryFiles contain base64"


def normalize_base_url(value: str | None) -> str:
    """Accept an origin, an /api prefix, or the complete assets API base."""
    raw = (value or BASE).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base URL must be an http:// or https:// URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, a query, or a fragment")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/assets"):
        path = f"{path}/assets" if path.endswith("/api") else f"{path}/api/assets"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _read_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        try:
            return json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"StyleKit returned invalid JSON from {url}") from error


def _require_string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"asset contract requires {field} to be a string")
    return value


def _summary(value: object, label: str = "asset summary") -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"asset contract requires {label} to be an object")
    result = dict(value)
    for field in ("id", "kind", "name", "description"):
        _require_string(result.get(field), f"{label}.{field}", allow_empty=(field == "description"))
    tags = result.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"asset contract requires {label}.tags to be a string array")
    availability = result.get("availability")
    if not isinstance(availability, str) or availability not in AVAILABILITY:
        raise ValueError(f"asset contract has unsupported {label}.availability: {availability!r}")
    content_level = result.get("contentLevel")
    if not isinstance(content_level, str) or content_level not in CONTENT_LEVELS:
        raise ValueError(f"asset contract has unsupported {label}.contentLevel: {content_level!r}")
    for field in ("nameZh", "sourceRef", "websiteUrl"):
        if result.get(field) is not None and not isinstance(result[field], str):
            raise ValueError(f"asset contract requires {label}.{field} to be a string")
    value = result.get("sourceUrls")
    if value is not None and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
        raise ValueError(f"asset contract requires {label}.sourceUrls to be a string array")
    for field in ("license", "attribution", "capabilities"):
        value = result.get(field)
        if value is not None and not isinstance(value, (str, dict, list)):
            raise ValueError(f"asset contract requires {label}.{field} to be JSON metadata")
    return result


def validate_list(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != "1":
        schema = payload.get("schemaVersion") if isinstance(payload, dict) else None
        raise ValueError(f"unsupported StyleKit assets schemaVersion: {schema!r}")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("asset catalogue response must contain an assets array")
    for index, asset in enumerate(assets):
        assets[index] = _summary(asset, f"assets[{index}]")

    kind_counts = payload.get("kindCounts")
    if not isinstance(kind_counts, dict) or not all(
        isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for key, value in kind_counts.items()
    ):
        raise ValueError("asset catalogue response requires kindCounts with non-negative integer values")
    for field in ("total", "offset", "limit"):
        number = payload.get(field)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ValueError(f"asset catalogue response requires a non-negative integer {field}")
    if payload["limit"] < 1:
        raise ValueError("asset catalogue response limit must be positive")
    if not isinstance(payload.get("hasMore"), bool):
        raise ValueError("asset catalogue response requires boolean hasMore")
    if len(assets) > payload["limit"]:
        raise ValueError("asset catalogue returned more records than the requested limit")
    if payload["total"] < len(assets):
        raise ValueError("asset catalogue total is smaller than the returned page")
    return dict(payload)


def _detail_metadata(payload: dict) -> dict:
    metadata = payload.get("metadata")
    if metadata is None:
        # Accept the equivalent flattened detail shape while older MCP clients
        # transition to the shared nested-metadata contract.
        metadata = {key: payload.get(key) for key in (
            "id", "kind", "name", "description", "tags", "availability", "contentLevel",
            "nameZh", "sourceRef", "websiteUrl", "sourceUrls", "license", "attribution", "capabilities",
        )}
    return _summary(metadata)


def validate_detail(payload: object, expected_kind: str, expected_id: str) -> dict:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != "1":
        schema = payload.get("schemaVersion") if isinstance(payload, dict) else None
        raise ValueError(f"unsupported StyleKit asset detail schemaVersion: {schema!r}")
    metadata = _detail_metadata(payload)
    if metadata["kind"] != expected_kind:
        raise ValueError(f"asset kind mismatch: expected '{expected_kind}', got '{metadata['kind']}'")
    if metadata["id"] != expected_id:
        raise ValueError(f"asset id mismatch: expected '{expected_id}', got '{metadata['id']}'")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("asset detail response must contain a data object")
    files = data.get("files")
    if files is not None and (
        not isinstance(files, dict) or not all(isinstance(path, str) and isinstance(content, str) for path, content in files.items())
    ):
        raise ValueError("asset detail data.files must map relative paths to strings")
    binary_files = data.get("binaryFiles")
    if binary_files is not None and (not isinstance(binary_files, list) or not all(isinstance(path, str) for path in binary_files)):
        raise ValueError("asset detail data.binaryFiles must be a string array")
    if files is not None and binary_files is not None and not set(binary_files).issubset(files):
        raise ValueError("asset detail data.binaryFiles must refer to keys in data.files")
    if data.get("sourceFilesIncluded") is not None and not isinstance(data["sourceFilesIncluded"], bool):
        raise ValueError("asset detail data.sourceFilesIncluded must be boolean")
    encoding = data.get("fileEncoding")
    if encoding is not None and not isinstance(encoding, str):
        raise ValueError("asset detail data.fileEncoding must be a string")
    if encoding is not None and encoding != BINARY_ENCODING:
        raise ValueError("asset detail data.fileEncoding is not a supported encoding contract")
    for field in ("dependencies", "devDependencies"):
        values = data.get(field)
        if values is not None and (
            not isinstance(values, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in values.items())
        ):
            raise ValueError(f"asset detail data.{field} must map package names to version strings")
    result = dict(payload)
    result["metadata"] = metadata

    code = result.get("code")
    if code is not None and not (
        isinstance(code, str) or isinstance(code, list) and all(isinstance(item, str) for item in code)
    ):
        raise ValueError("asset detail code must be a string or an array of strings")
    for field in ("dependencies", "sourceUrls"):
        value = result.get(field)
        if value is not None and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
            raise ValueError(f"asset detail {field} must be a string array")
    for field in ("source", "attribution", "license"):
        value = result.get(field)
        if value is not None and not isinstance(value, (str, dict, list)):
            raise ValueError(f"asset detail {field} must be JSON metadata")

    content_level = metadata["contentLevel"]
    if metadata["availability"] == "restricted" or content_level == "restricted":
        # Keep identifying and license metadata, but never serialize reusable
        # source for an item the catalogue marks restricted.
        for field in ("data", "code", "dependencies"):
            result.pop(field, None)
            metadata.pop(field, None)
        result["_stylekitAccess"] = {
            "usable": False,
            "reason": "StyleKit marks this asset restricted; obtain and verify the required entitlement before use.",
        }
    elif metadata["availability"] == "external":
        for field in ("data", "code", "dependencies"):
            result.pop(field, None)
            metadata.pop(field, None)
        result["_stylekitAccess"] = {
            "usable": "review-required",
            "reason": "This asset points outside StyleKit; review its source and license before retrieving or reusing it.",
        }
    elif content_level == "metadata":
        for field in ("data", "code", "dependencies"):
            result.pop(field, None)
            metadata.pop(field, None)
        result["_stylekitAccess"] = {
            "usable": "metadata-only",
            "reason": "This record contains metadata only; do not invent or imply that source code is available.",
        }
    elif content_level == "remote" and (
        metadata["kind"] == "template"
        and isinstance(data.get("files"), dict)
        and data.get("sourceFilesIncluded") is True
    ):
        result["_stylekitAccess"] = {
            "usable": "files-available",
            "reason": "The response includes the project files; materialize them only to a new, explicitly chosen directory.",
        }
    elif content_level == "remote":
        result["_stylekitAccess"] = {
            "usable": "fetch-required",
            "reason": "This asset is available from a separate official download route; use an explicit verified download action.",
        }
    else:
        result["_stylekitAccess"] = {"usable": True}
    return result


def _parse_text_block(value: str) -> object:
    text = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("MCP text block is not complete JSON; save the complete structuredContent when available") from error


def _extract_mcp(payload: object) -> tuple[object, str]:
    if not isinstance(payload, dict):
        raise ValueError("MCP result must be a JSON object")
    if payload.get("isError") is True:
        raise ValueError("MCP tool result isError=true; save a successful tool result")
    structured = payload.get("structuredContent", payload.get("structured_content"))
    if structured is not None:
        return structured, "mcp-structuredContent"
    nested = payload.get("result")
    if isinstance(nested, dict):
        return _extract_mcp(nested)
    content = payload.get("content")
    if isinstance(content, list):
        errors = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            try:
                return _parse_text_block(block["text"]), "mcp-text-content"
            except ValueError as error:
                errors.append(str(error))
        suffix = f": {errors[-1]}" if errors else ""
        raise ValueError("MCP result has no usable structuredContent or JSON text block" + suffix)
    raise ValueError("MCP result has no structuredContent or JSON text block")


def _load_file(path: Path, from_mcp: bool) -> tuple[object, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON asset data from {path}: {error}") from error
    if from_mcp:
        return _extract_mcp(payload)
    if isinstance(payload, dict) and payload.get("isError") is True:
        raise ValueError("saved payload isError=true; use a successful StyleKit response")
    return payload, "json-file"


def search_assets(
    query: str = "",
    kind: str | None = None,
    offset: int = 0,
    limit: int = 15,
    base_url: str | None = None,
) -> tuple[dict, str]:
    if offset < 0 or limit < 1 or limit > 100:
        raise ValueError("offset must be >= 0 and limit must be between 1 and 100")
    base = normalize_base_url(base_url)
    params = {"q": query, "offset": str(offset), "limit": str(limit)}
    if kind:
        params["kind"] = kind
    url = f"{base}?{urllib.parse.urlencode(params)}"
    return validate_list(_read_json(url)), url


def fetch_asset(kind: str, asset_id: str, base_url: str | None = None) -> tuple[dict, str]:
    base = normalize_base_url(base_url)
    encoded_kind = urllib.parse.quote(kind, safe="")
    encoded_id = urllib.parse.quote(asset_id, safe="")
    url = f"{base}/{encoded_kind}/{encoded_id}"
    return validate_detail(_read_json(url), kind, asset_id), url


def _with_source(payload: dict, kind: str, contract: str, url: str | None) -> dict:
    result = dict(payload)
    inherited = result.get("_stylekitSource")
    prior = inherited if isinstance(inherited, dict) else {}
    source = {
        "kind": kind,
        "contract": contract,
        "degraded": False,
    }
    if url:
        source["url"] = url
    # Keep useful provenance for saved API records without trusting the saved
    # contract/degraded flags as validation evidence.
    for key in ("url", "requestId"):
        if key not in source and isinstance(prior.get(key), str):
            source[key] = prior[key]
    result["_stylekitSource"] = source
    return result


def print_list(payload: dict, query: str, kind: str | None) -> None:
    print(f"ASSETS: {payload['total']} matching · offset {payload['offset']} · returned {len(payload['assets'])}")
    print(f"FILTER: kind={kind or 'all'} · query={query or '(all)'} · hasMore={str(payload['hasMore']).lower()}")
    counts = payload["kindCounts"]
    if counts:
        print("BY KIND: " + " · ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    for asset in payload["assets"]:
        tags = ", ".join(asset["tags"][:5])
        print(f"  {asset['kind']}/{asset['id']} [{asset['availability']}/{asset['contentLevel']}] — {asset['name']}")
        print(f"    {asset['description']}")
        if tags:
            print(f"    tags: {tags}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        # Asset retrieval must stay on the exact API route returned by StyleKit.
        return None


def _verified_template_download_url(asset: dict, base_url: str | None) -> str:
    metadata = asset["metadata"]
    if metadata["kind"] != "template" or metadata["availability"] != "remote" or metadata["contentLevel"] != "remote":
        raise ValueError("--download-to is only supported for remote template assets")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata["id"]):
        raise ValueError("template ID must be a lowercase slug before downloading")
    data = asset.get("data")
    download_url = data.get("downloadUrl") if isinstance(data, dict) else None
    if not isinstance(download_url, str) or not download_url:
        raise ValueError("this template response has no downloadUrl")
    parsed = urlsplit(download_url)
    expected_path = f"/api/templates/{urllib.parse.quote(metadata['id'], safe='')}/download"
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("template download URL is not a clean HTTP(S) URL")
    if parsed.path != expected_path:
        raise ValueError("template download URL does not match the exact official template route")
    origin = urlsplit(normalize_base_url(base_url))
    try:
        local_host = origin.hostname in {"localhost", "127.0.0.1", "::1"} or bool(origin.hostname and ipaddress.ip_address(origin.hostname).is_loopback)
    except ValueError:
        local_host = False
    if local_host:
        if parsed.scheme != origin.scheme or parsed.netloc != origin.netloc:
            raise ValueError("local API template downloads must remain on the same origin")
    elif parsed.scheme != "https" or parsed.hostname not in {"stylekit.top", "www.stylekit.top"}:
        raise ValueError("template download must use StyleKit's official HTTPS host")
    if data.get("downloadMethod") != "GET" or data.get("downloadFormat") != "zip":
        raise ValueError("template download metadata must declare GET and zip")
    return download_url


def download_template(asset: dict, destination: Path, base_url: str | None = None) -> dict:
    url = _verified_template_download_url(asset, base_url)
    if destination.suffix.casefold() != ".zip":
        raise ValueError("template download destination must end in .zip")
    if not destination.parent.is_dir():
        raise ValueError(f"destination directory does not exist: {destination.parent}")
    request = urllib.request.Request(url, headers={"Accept": "application/zip"})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=30) as response:
        content = response.read(MAX_TEMPLATE_BYTES + 1)
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
    if len(content) > MAX_TEMPLATE_BYTES:
        raise ValueError("template ZIP exceeds the 50 MiB download limit")
    if content_type not in ("application/zip", "application/octet-stream") or not zipfile.is_zipfile(io.BytesIO(content)):
        raise ValueError("StyleKit template endpoint did not return a valid ZIP archive")
    try:
        with destination.open("xb") as output:
            output.write(content)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite existing file: {destination}") from error
    return {
        "path": str(destination.resolve()),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _decode_project_files(asset: dict) -> list[tuple[PurePosixPath, bytes]]:
    metadata = asset["metadata"]
    data = asset.get("data")
    if metadata["kind"] != "template" or metadata["availability"] != "remote" or metadata["contentLevel"] != "remote":
        raise ValueError("--output-dir is only supported for remote template assets")
    if not isinstance(data, dict) or data.get("sourceFilesIncluded") is not True:
        raise ValueError("this response contains no template source files; use --download-to for the official ZIP")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("template source response must contain a non-empty data.files object")
    if len(files) > MAX_PROJECT_FILES:
        raise ValueError(f"template contains more than {MAX_PROJECT_FILES} files")
    binary_files = data.get("binaryFiles", [])
    if not isinstance(binary_files, list) or not all(isinstance(path, str) for path in binary_files):
        raise ValueError("template data.binaryFiles must be a string array")
    if not set(binary_files).issubset(files):
        raise ValueError("template binaryFiles contains a path absent from data.files")
    encoding = data.get("fileEncoding")
    if encoding is not None and encoding != BINARY_ENCODING:
        raise ValueError("template fileEncoding does not match the documented UTF-8/base64 contract")
    if binary_files and encoding != BINARY_ENCODING:
        raise ValueError("template fileEncoding is required when binary files are present")

    decoded = []
    total_bytes = 0
    binary_set = set(binary_files)
    for raw_path, content in files.items():
        if (
            not raw_path or "\\" in raw_path or "\x00" in raw_path or ":" in raw_path
            or raw_path.startswith("/") or raw_path.endswith("/") or "//" in raw_path
            or any(char in raw_path for char in '<>"|?*')
        ):
            raise ValueError(f"unsafe template file path: {raw_path!r}")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or any(part in ("", ".", "..") or part.endswith((".", " ")) for part in relative.parts):
            raise ValueError(f"unsafe template file path: {raw_path!r}")
        if raw_path in binary_set:
            try:
                content_bytes = base64.b64decode(content, validate=True)
            except ValueError as error:
                raise ValueError(f"template binary file is not valid base64: {raw_path}") from error
        else:
            content_bytes = content.encode("utf-8")
        total_bytes += len(content_bytes)
        if total_bytes > MAX_PROJECT_BYTES:
            raise ValueError("template source exceeds the 100 MiB materialization limit")
        decoded.append((relative, content_bytes))
    return decoded


def materialize_template(asset: dict, destination: Path) -> dict:
    files = _decode_project_files(asset)
    if destination.is_symlink():
        raise ValueError(f"refusing to write through a symlink destination: {destination}")
    destination = destination.resolve()
    if destination.exists():
        raise ValueError(f"refusing to overwrite existing path: {destination}")
    if not destination.parent.is_dir():
        raise ValueError(f"destination parent directory does not exist: {destination.parent}")
    staging = Path(tempfile.mkdtemp(prefix=".stylekit-template-", dir=str(destination.parent)))
    try:
        for relative, content in files:
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(content)
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "path": str(destination),
        "files": len(files),
        "bytes": sum(len(content) for _, content in files),
    }


def print_detail(asset: dict) -> None:
    metadata = asset["metadata"]
    print(f"ASSET: {metadata['kind']}/{metadata['id']} — {metadata['name']}")
    print(f"AVAILABILITY: {metadata['availability']} · contentLevel={metadata['contentLevel']}")
    if metadata.get("nameZh"):
        print(f"NAME ZH: {metadata['nameZh']}")
    print(f"DESCRIPTION: {metadata['description']}")
    if asset.get("_stylekitAccess", {}).get("reason"):
        print(f"ACCESS: {asset['_stylekitAccess']['reason']}")
    for label, key in (("LICENSE", "license"), ("ATTRIBUTION", "attribution"), ("SOURCE", "source"), ("SOURCE URLS", "sourceUrls"), ("WEBSITE URL", "websiteUrl"), ("SOURCE REF", "sourceRef"), ("CAPABILITIES", "capabilities"), ("DEPENDENCIES", "dependencies")):
        value = asset.get(key)
        if value is None:
            value = metadata.get(key)
        if value is not None:
            print(label)
            print(json.dumps(value, ensure_ascii=False, indent=2))
    if asset.get("data") is not None:
        print("DATA")
        print(json.dumps(asset["data"], ensure_ascii=False, indent=2))
    if asset.get("code") is not None:
        print("CODE")
        print(json.dumps(asset["code"], ensure_ascii=False, indent=2))


def _read_local_asset(args: argparse.Namespace, expected_kind: str | None = None, expected_id: str | None = None):
    path = args.spec or args.from_file
    payload, source_kind = _load_file(path, from_mcp=bool(args.from_file))
    if expected_kind is None:
        result = validate_list(payload)
    else:
        result = validate_detail(payload, expected_kind, expected_id or "")
    source = _with_source(result, source_kind, CONTRACT, None)
    return source


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--spec", type=Path, help="Read a saved StyleKit asset API response offline")
    group.add_argument("--from-file", type=Path, help="Read a saved MCP tool result (structuredContent or JSON text) offline")
    parser.add_argument("--base-url", help="StyleKit API base, origin, or /api prefix (default: %(default)s)", default=BASE)
    parser.add_argument("--json", action="store_true", help="Print validated machine-readable JSON")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search", help="Search the public asset catalogue")
    search.add_argument("query", nargs="?", default="", help="Optional words matched against names, descriptions, tags and IDs")
    search.add_argument("--kind", help="Limit to one catalogue kind; omit to search across kinds")
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--limit", type=int, default=15)
    _add_input_options(search)

    get = subparsers.add_parser("get", help="Fetch one exact asset by kind and ID")
    get.add_argument("kind")
    get.add_argument("id")
    output = get.add_mutually_exclusive_group()
    output.add_argument("--download-to", type=Path, help="Explicitly download a verified public template ZIP to this new path")
    output.add_argument("--output-dir", type=Path, help="Write returned template source files to this new directory")
    _add_input_options(get)

    args = parser.parse_args()
    try:
        if args.command == "search":
            if args.offset < 0 or args.limit < 1 or args.limit > 100:
                raise ValueError("offset must be >= 0 and limit must be between 1 and 100")
            if args.spec or args.from_file:
                result = _read_local_asset(args)
                visible = [
                    asset for asset in result["assets"]
                    if (not args.kind or asset["kind"] == args.kind)
                    and args.query.casefold() in json.dumps(asset, ensure_ascii=False).casefold()
                ]
                result["total"] = len(visible)
                result["offset"] = args.offset
                result["limit"] = args.limit
                result["assets"] = visible[args.offset:args.offset + args.limit]
                result["hasMore"] = args.offset + len(result["assets"]) < len(visible)
                result["_stylekitSource"]["scope"] = "saved response only; no additional API pages were fetched"
            else:
                result, url = search_assets(args.query, args.kind, args.offset, args.limit, args.base_url)
                result = _with_source(result, "http-api", CONTRACT, url)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_list(result, args.query, args.kind)
        else:
            if args.spec or args.from_file:
                result = _read_local_asset(args, args.kind, args.id)
            else:
                result, url = fetch_asset(args.kind, args.id, args.base_url)
                result = _with_source(result, "http-api", CONTRACT, url)
            if args.download_to:
                download = download_template(result, args.download_to, args.base_url)
                result["_stylekitDownload"] = download
            if args.output_dir:
                materialized = materialize_template(result, args.output_dir)
                result["_stylekitMaterialized"] = materialized
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_detail(result)
                if args.download_to:
                    print(f"DOWNLOADED ZIP: {download['path']} ({download['bytes']} bytes, sha256:{download['sha256']})")
                if args.output_dir:
                    print(f"MATERIALIZED: {materialized['path']} ({materialized['files']} files, {materialized['bytes']} bytes)")
    except (OSError, urllib.error.URLError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return_code = 2
        sys.exit(return_code)


if __name__ == "__main__":
    main()
