from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any


REQUIRED_DIRECTORY_FIELDS = {"path", "purpose", "class", "owner", "lifecycle", "tracking", "responsibility"}
VALID_CLASSES = {
    "archive",
    "configuration",
    "docs",
    "durable_evidence",
    "generated_output",
    "model_link",
    "scratch_cache",
    "source",
    "tests",
    "vendor",
    "workspace_collection",
}
VALID_TRACKING = {"generated", "ignored", "symlink", "tracked"}
VALID_LIFECYCLES = {"durable", "ephemeral", "historical", "reference"}
MALFORMED_NAME_RE = re.compile(r"(?:[\\:]|\$\{|\bundefined\b|[\x00-\x1f])", re.IGNORECASE)
TASK_NAME_RE = re.compile(r"^(?:chore|codex|feature|fix|scratch|task|temp|tmp)[-_]|^20\d{2}[-_]\d{2}", re.IGNORECASE)


class FolderPolicyError(ValueError):
    pass


def load_folder_policy(path: Path) -> dict[str, Any]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    validate_folder_policy(payload)
    return payload


def _directory_templates(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for group in policy.get("name_groups", []):
        if not isinstance(group, dict):
            continue
        names = group.get("names", [])
        metadata = {key: value for key, value in group.items() if key != "names"}
        for name in names:
            templates[str(name)] = dict(metadata)
    for name, metadata in policy.get("root_defaults", {}).items():
        if isinstance(metadata, dict):
            templates[str(name)] = {**templates.get(str(name), {}), **metadata}
    return templates


def _repo_rows(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = policy.get("repos", {})
    if not isinstance(rows, dict):
        raise FolderPolicyError("folder policy repos must be a table")
    return {str(repo_id): dict(row) for repo_id, row in rows.items() if isinstance(row, dict)}


def _legacy_exception_map(repo_row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in repo_row.get("legacy_exceptions", []):
        if isinstance(row, dict) and str(row.get("path", "")).strip():
            result[str(row["path"])] = dict(row)
    return result


def _active_exception(row: dict[str, Any], *, today: date | None = None) -> bool:
    expiry = str(row.get("expires", "")).strip()
    if not expiry:
        return False
    try:
        return date.fromisoformat(expiry) >= (today or date.today())
    except ValueError:
        return False


def validate_folder_policy(policy: dict[str, Any]) -> None:
    if int(policy.get("schema_version", 0) or 0) != 1:
        raise FolderPolicyError("folder policy schema_version must be 1")
    if not str(policy.get("policy_id", "")).strip():
        raise FolderPolicyError("folder policy requires policy_id")
    templates = _directory_templates(policy)
    repos = _repo_rows(policy)
    collections = policy.get("collections", {})
    if not isinstance(collections, dict):
        raise FolderPolicyError("folder policy collections must be a table")
    for collection_id, row in collections.items():
        if not isinstance(row, dict):
            raise FolderPolicyError(f"folder policy collection {collection_id} must be a table")
        missing = sorted(REQUIRED_DIRECTORY_FIELDS - {"responsibility"} - row.keys())
        if missing:
            raise FolderPolicyError(
                f"folder policy collection {collection_id} is missing: {', '.join(missing)}"
            )
        path = Path(str(row.get("path", "")))
        if path.is_absolute() or ".." in path.parts:
            raise FolderPolicyError(f"folder policy collection {collection_id} path must stay within the workspace")
    for repo_id, repo_row in repos.items():
        if not str(repo_row.get("profile", "")).strip():
            raise FolderPolicyError(f"folder policy repo {repo_id} requires profile")
        declared_roots = repo_row.get("declared_roots", [])
        if not isinstance(declared_roots, list):
            raise FolderPolicyError(f"folder policy repo {repo_id} declared_roots must be a list")
        overrides = repo_row.get("directories", {})
        if not isinstance(overrides, dict):
            raise FolderPolicyError(f"folder policy repo {repo_id} directories must be a table")
        for root_name in declared_roots:
            root_name = str(root_name)
            metadata = {"path": root_name, **templates.get(root_name, {})}
            override = overrides.get(root_name, {})
            if isinstance(override, dict):
                metadata.update(override)
            missing = sorted(REQUIRED_DIRECTORY_FIELDS - metadata.keys())
            if missing:
                raise FolderPolicyError(
                    f"folder policy repo {repo_id} root {root_name} is missing: {', '.join(missing)}"
                )
            if metadata["class"] not in VALID_CLASSES:
                raise FolderPolicyError(f"folder policy repo {repo_id} root {root_name} has invalid class")
            if metadata["tracking"] not in VALID_TRACKING:
                raise FolderPolicyError(f"folder policy repo {repo_id} root {root_name} has invalid tracking")
            if metadata["lifecycle"] not in VALID_LIFECYCLES:
                raise FolderPolicyError(f"folder policy repo {repo_id} root {root_name} has invalid lifecycle")
        for path, exception in _legacy_exception_map(repo_row).items():
            if not str(exception.get("reason", "")).strip() or not str(exception.get("expires", "")).strip():
                raise FolderPolicyError(f"folder policy repo {repo_id} exception {path} requires reason and expires")
        legacy_hashes = repo_row.get("legacy_root_hashes", [])
        if not isinstance(legacy_hashes, list) or any(not re.fullmatch(r"[0-9a-f]{24}", str(item)) for item in legacy_hashes):
            raise FolderPolicyError(f"folder policy repo {repo_id} legacy_root_hashes must contain 24-character SHA256 prefixes")


def resolve_repo_contract(
    policy: dict[str, Any],
    repo_id: str,
    *,
    archetype: str = "",
    repo_path: str = "",
) -> dict[str, Any]:
    repo_row = _repo_rows(policy).get(repo_id)
    if repo_row is None:
        return {
            "schema_version": 1,
            "policy_id": str(policy.get("policy_id", "")),
            "repo_id": repo_id,
            "status": "missing_contract",
            "mode": str(policy.get("default_mode", "warn")),
            "profile": "",
            "archetype": archetype,
            "repo_path": repo_path,
            "directories": [],
            "standard_transients": list(policy.get("standard_transients", [])),
            "generic_names": list(policy.get("generic_names", [])),
        }
    templates = _directory_templates(policy)
    exceptions = _legacy_exception_map(repo_row)
    overrides = repo_row.get("directories", {})
    directories: list[dict[str, Any]] = []
    for item in repo_row.get("declared_roots", []):
        root_name = str(item)
        metadata: dict[str, Any] = {"path": root_name, **templates.get(root_name, {})}
        override = overrides.get(root_name, {})
        if isinstance(override, dict):
            metadata.update(override)
        exception = exceptions.get(root_name)
        metadata["legacy_exception"] = dict(exception) if exception else {}
        metadata.setdefault("qualified", root_name not in set(policy.get("generic_names", [])))
        metadata.setdefault("required", False)
        metadata.setdefault("canonical_target", "")
        metadata.setdefault("generator", "")
        metadata.setdefault("allow_shared_responsibility", False)
        directories.append(metadata)
    fingerprint_payload = {
        "policy_id": policy.get("policy_id"),
        "repo_id": repo_id,
        "profile": repo_row.get("profile"),
        "directories": directories,
        "legacy_exceptions": list(repo_row.get("legacy_exceptions", [])),
        "legacy_root_hashes": list(repo_row.get("legacy_root_hashes", [])),
        "standard_transients": policy.get("standard_transients", []),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "policy_id": str(policy.get("policy_id", "")),
        "repo_id": repo_id,
        "status": "declared",
        "mode": str(repo_row.get("mode") or policy.get("default_mode", "warn")),
        "profile": str(repo_row.get("profile", "")),
        "archetype": archetype,
        "repo_path": repo_path,
        "audit_only": bool(repo_row.get("audit_only", False)),
        "directories": directories,
        "legacy_exceptions": list(repo_row.get("legacy_exceptions", [])),
        "legacy_root_hashes": list(repo_row.get("legacy_root_hashes", [])),
        "standard_transients": list(policy.get("standard_transients", [])),
        "generic_names": list(policy.get("generic_names", [])),
        "contract_fingerprint": fingerprint,
        "placement_rule": "use an existing declared root or update the folder contract before creating a top-level directory",
    }


def workspace_contract(policy: dict[str, Any]) -> dict[str, Any]:
    workspace = policy.get("workspace", {})
    if not isinstance(workspace, dict):
        workspace = {}
    return {
        "directories": sorted(str(item) for item in workspace.get("directories", [])),
        "files": sorted(str(item) for item in workspace.get("files", [])),
        "audit_only_prefixes": sorted(str(item) for item in workspace.get("audit_only_prefixes", [])),
        "collections": policy.get("collections", {}),
    }


def assess_collection_roots(workspace_root: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    collections = contract.get("collections", {})
    if not isinstance(collections, dict):
        return rows
    for collection_id, metadata in sorted(collections.items()):
        if not isinstance(metadata, dict):
            continue
        relative = Path(str(metadata.get("path", "")))
        root = workspace_root / relative
        children: list[Path] = []
        if root.is_dir():
            try:
                children = [child for child in root.iterdir() if child.is_dir() and child.name != ".git"]
            except OSError:
                children = []
        malformed_children = sorted(child.name for child in children if MALFORMED_NAME_RE.search(child.name))
        nested_git_roots = sum(1 for child in children if (child / ".git").exists())
        status = "missing" if not root.exists() else "fail" if malformed_children else "pass"
        rows.append(
            {
                "collection_id": str(collection_id),
                "path": relative.as_posix(),
                "purpose": str(metadata.get("purpose", "")),
                "class": str(metadata.get("class", "workspace_collection")),
                "owner": str(metadata.get("owner", "")),
                "lifecycle": str(metadata.get("lifecycle", "")),
                "tracking": str(metadata.get("tracking", "")),
                "status": status,
                "child_directory_count": len(children),
                "direct_git_root_count": nested_git_roots,
                "malformed_child_count": len(malformed_children),
                "malformed_children": malformed_children,
                "next_action": (
                    "restore or retire the declared collection root"
                    if status == "missing"
                    else "quarantine malformed collection children after preservation"
                    if status == "fail"
                    else "classify new child roots before treating them as durable projects"
                ),
            }
        )
    return rows


def _tracked_top_level(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    roots: set[str] = set()
    for chunk in result.stdout.split(b"\x00"):
        if not chunk:
            continue
        relative = chunk.decode("utf-8", errors="replace")
        if "/" in relative:
            roots.add(relative.split("/", 1)[0])
    return roots


def _ignored(repo_root: Path, name: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", "--", name],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def discover_top_level(repo_root: Path) -> list[dict[str, Any]]:
    tracked = _tracked_top_level(repo_root)
    rows: list[dict[str, Any]] = []
    try:
        children = sorted(repo_root.iterdir(), key=lambda item: item.name)
    except OSError:
        return rows
    for child in children:
        if child.name == ".git" or (not child.is_dir() and not child.is_symlink()):
            continue
        if child.is_symlink():
            tracking = "symlink"
        elif child.name in tracked:
            tracking = "tracked"
        elif _ignored(repo_root, child.name):
            tracking = "ignored"
        else:
            tracking = "untracked"
        rows.append(
            {
                "path": child.name,
                "tracking": tracking,
                "is_symlink": child.is_symlink(),
                "symlink_target": str(child.readlink()) if child.is_symlink() else "",
                "malformed_name": bool(MALFORMED_NAME_RE.search(child.name)),
                "task_specific_name": bool(TASK_NAME_RE.search(child.name)),
            }
        )
    return rows


def _tracking_matches(expected: str, actual: str) -> bool:
    if expected == "generated":
        return actual in {"ignored", "tracked"}
    return expected == actual


def _next_action(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "use an existing declared root for new files"
    priority = {
        "malformed_root_name": 0,
        "generated_output_escape": 1,
        "undeclared_top_level_dir": 2,
        "tracking_policy_mismatch": 3,
        "symlink_target_mismatch": 4,
        "overlapping_root_responsibility": 5,
        "legacy_undeclared_top_level_dir": 6,
        "ambiguous_root_name": 7,
    }
    finding = min(findings, key=lambda row: priority.get(str(row.get("code", "")), 50))
    path = str(finding.get("path", "")).strip()
    path_label = json.dumps(path) if path else "the reported root"
    code = str(finding.get("code", ""))
    if code == "malformed_root_name":
        return f"preserve, quarantine, or rename {path_label}; then rerun `make verify-paths`"
    if code == "generated_output_escape":
        return f"move {path_label} into a declared ignored output root; then rerun `make verify-paths`"
    if code in {"undeclared_top_level_dir", "legacy_undeclared_top_level_dir"}:
        return f"declare or relocate {path_label} through `catalog/folder_organization.toml`; then rerun `make verify-paths`"
    if code in {"tracking_policy_mismatch", "symlink_target_mismatch"}:
        return f"reconcile the declared tracking/target policy for {path_label}; then rerun `make verify-paths`"
    return "resolve the first folder-organization finding, then rerun `make verify-paths`"


def assess_repo_layout(repo_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    actual = discover_top_level(repo_root)
    declared = {str(row.get("path", "")): row for row in contract.get("directories", [])}
    transients = {str(item) for item in contract.get("standard_transients", [])}
    generic_names = {str(item) for item in contract.get("generic_names", [])}
    legacy_exceptions = {
        str(item.get("path", "")): item
        for item in contract.get("legacy_exceptions", [])
        if isinstance(item, dict) and str(item.get("path", ""))
    }
    legacy_hashes = {str(item) for item in contract.get("legacy_root_hashes", [])}
    findings: list[dict[str, Any]] = []
    purpose_covered = 0
    declared_present = 0
    responsibility_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    if contract.get("status") != "declared":
        findings.append(
            {
                "code": "missing_folder_contract",
                "severity": "fail",
                "path": "",
                "message": "repo has no folder-organization contract",
            }
        )

    for row in actual:
        name = row["path"]
        metadata = declared.get(name)
        if row["malformed_name"]:
            findings.append(
                {
                    "code": "malformed_root_name",
                    "severity": "fail",
                    "path": name,
                    "message": "top-level directory contains a path fragment, placeholder, control character, or undefined marker",
                }
            )
        if metadata is None:
            if name in transients:
                if row["tracking"] not in {"ignored", "untracked"}:
                    findings.append(
                        {
                            "code": "generated_output_escape",
                            "severity": "fail",
                            "path": name,
                            "message": "runtime or generated output escaped its required ignored boundary",
                        }
                    )
                continue
            exception = legacy_exceptions.get(name, {})
            legacy_observed = _active_exception(exception) or hashlib.sha256(name.encode("utf-8")).hexdigest()[:24] in legacy_hashes
            findings.append(
                {
                    "code": "legacy_undeclared_top_level_dir" if legacy_observed else "undeclared_top_level_dir",
                    "severity": "warn" if legacy_observed else "fail",
                    "path": name,
                    "message": (
                        "pre-policy top-level directory remains outside the repository folder contract"
                        if legacy_observed
                        else "top-level directory is absent from the repository folder contract"
                    ),
                    "legacy_exception": exception,
                }
            )
            if row["task_specific_name"] and not legacy_observed:
                findings.append(
                    {
                        "code": "task_specific_root_name",
                        "severity": "fail",
                        "path": name,
                        "message": "task, branch, date, agent, and temporary names are not durable top-level categories",
                    }
                )
            continue
        declared_present += 1
        exception = metadata.get("legacy_exception", {}) if isinstance(metadata.get("legacy_exception"), dict) else {}
        exception_active = _active_exception(exception)
        if str(metadata.get("purpose", "")).strip():
            purpose_covered += 1
        if name in generic_names and not bool(metadata.get("qualified", False)):
            findings.append(
                {
                    "code": "ambiguous_root_name",
                    "severity": "warn" if exception_active or contract.get("mode") != "enforce" else "fail",
                    "path": name,
                    "message": "generic top-level name lacks a repo-specific qualified purpose",
                    "legacy_exception": exception,
                }
            )
        if not _tracking_matches(str(metadata.get("tracking", "")), str(row["tracking"])):
            findings.append(
                {
                    "code": "tracking_policy_mismatch",
                    "severity": "warn" if exception_active else "fail",
                    "path": name,
                    "message": f"expected {metadata.get('tracking')} but observed {row['tracking']}",
                    "legacy_exception": exception,
                }
            )
        if row["is_symlink"] and str(metadata.get("canonical_target", "")).strip():
            expected_target = Path(str(metadata["canonical_target"]))
            actual_target = Path(str(row["symlink_target"]))
            if actual_target != expected_target:
                findings.append(
                    {
                        "code": "symlink_target_mismatch",
                        "severity": "fail",
                        "path": name,
                        "message": f"expected symlink target {expected_target} but observed {actual_target}",
                    }
                )
        responsibility = str(metadata.get("responsibility", "")).strip()
        if responsibility:
            responsibility_rows[responsibility].append(metadata)

    for name, metadata in declared.items():
        if bool(metadata.get("required", False)) and name not in {row["path"] for row in actual}:
            findings.append(
                {
                    "code": "required_root_missing",
                    "severity": "fail",
                    "path": name,
                    "message": "required top-level directory is missing",
                }
            )

    for responsibility, rows in responsibility_rows.items():
        if len(rows) < 2 or all(bool(row.get("allow_shared_responsibility", False)) for row in rows):
            continue
        findings.append(
            {
                "code": "overlapping_root_responsibility",
                "severity": "warn" if contract.get("mode") != "enforce" else "fail",
                "path": ",".join(sorted(str(row["path"]) for row in rows)),
                "message": f"multiple top-level roots claim responsibility `{responsibility}`",
            }
        )

    counts = Counter(str(row["code"]) for row in findings)
    fail_count = sum(1 for row in findings if row["severity"] == "fail")
    warn_count = sum(1 for row in findings if row["severity"] == "warn")
    actual_nontransient_count = sum(
        1 for row in actual if row["path"] not in transients or row["path"] in declared
    )
    purpose_coverage = round((purpose_covered / actual_nontransient_count * 100.0), 2) if actual_nontransient_count else 100.0
    status = "fail" if fail_count else "warn" if warn_count else "pass"
    return {
        "schema_version": 1,
        "repo_id": str(contract.get("repo_id", "")),
        "status": status,
        "mode": str(contract.get("mode", "warn")),
        "profile": str(contract.get("profile", "")),
        "contract_fingerprint": str(contract.get("contract_fingerprint", "")),
        "actual_directories": actual,
        "findings": findings,
        "metrics": {
            "top_level_dir_count": actual_nontransient_count,
            "declared_present_count": declared_present,
            "purpose_covered_count": purpose_covered,
            "top_level_purpose_coverage_pct": purpose_coverage,
            "undeclared_top_level_dir_count": counts.get("undeclared_top_level_dir", 0)
            + counts.get("legacy_undeclared_top_level_dir", 0),
            "legacy_undeclared_top_level_dir_count": counts.get("legacy_undeclared_top_level_dir", 0),
            "ambiguous_root_name_count": counts.get("ambiguous_root_name", 0),
            "overlapping_root_responsibility_count": counts.get("overlapping_root_responsibility", 0),
            "invalid_runtime_root_count": counts.get("malformed_root_name", 0),
            "tracking_policy_mismatch_count": counts.get("tracking_policy_mismatch", 0),
            "new_top_level_dir_violation_count": counts.get("undeclared_top_level_dir", 0),
        },
        "next_action": _next_action(findings),
    }


def migration_actions(contract: dict[str, Any], assessment: dict[str, Any]) -> list[dict[str, Any]]:
    actual_names = {str(row.get("path", "")) for row in assessment.get("actual_directories", [])}
    actions: list[dict[str, Any]] = []
    for row in contract.get("directories", []):
        source = str(row.get("path", ""))
        target = str(row.get("canonical_target", "")).strip()
        if not target or source not in actual_names:
            continue
        action = {
            "id": f"folder-migration:{contract.get('repo_id')}:{source}",
            "type": "review_folder_migration",
            "scope": "repo_folder_organization",
            "source_path": source,
            "target_path": target,
            "safety": "review_required",
            "requires_review": True,
            "apply_supported": False,
            "status": "planned",
            "expected_contract_fingerprint": str(contract.get("contract_fingerprint", "")),
            "reference_scan": f"rg -n --hidden --glob '!.git/**' {json.dumps(source)} .",
            "rollback": f"move `{target}` back to `{source}` and restore updated references",
            "acceptance": "zero stale references, preserved git state, and repo-local validation passes",
        }
        action["plan_digest"] = _migration_plan_digest(action)
        actions.append(action)
    return actions


def _migration_plan_digest(action: dict[str, Any]) -> str:
    payload = {
        key: action.get(key)
        for key in (
            "id",
            "type",
            "source_path",
            "target_path",
            "expected_contract_fingerprint",
            "reference_scan",
            "rollback",
            "acceptance",
        )
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_migration_action(
    action: dict[str, Any], contract: dict[str, Any], assessment: dict[str, Any]
) -> dict[str, str | bool]:
    """Validate a reviewed plan without performing a folder move."""
    if str(action.get("expected_contract_fingerprint", "")) != str(contract.get("contract_fingerprint", "")):
        return {"status": "refused", "reason": "contract_fingerprint_mismatch", "apply_supported": False}
    if str(action.get("plan_digest", "")) != _migration_plan_digest(action):
        return {"status": "refused", "reason": "plan_digest_mismatch", "apply_supported": False}
    actual_names = {str(row.get("path", "")) for row in assessment.get("actual_directories", [])}
    if str(action.get("source_path", "")) not in actual_names:
        return {"status": "refused", "reason": "source_path_missing", "apply_supported": False}
    declared_targets = {
        (str(row.get("path", "")), str(row.get("canonical_target", "")))
        for row in contract.get("directories", [])
        if str(row.get("canonical_target", "")).strip()
    }
    if (str(action.get("source_path", "")), str(action.get("target_path", ""))) not in declared_targets:
        return {"status": "refused", "reason": "undeclared_migration", "apply_supported": False}
    return {"status": "review_current", "reason": "manual_migration_only", "apply_supported": False}
