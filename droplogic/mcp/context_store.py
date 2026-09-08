"""Filesystem-backed agent context for DropLogic MCP."""

from pathlib import Path
from typing import Any, Dict, List, Optional


class DropLogicMCPContextStore:
    """Serve packaged and user-supplied context files for one system profile."""

    def __init__(self, system_name: str = "boxmini", context_dir: Optional[str] = None):
        self.system_name = (system_name or "boxmini").lower()
        self.context_dir = (
            Path(context_dir).expanduser().resolve()
            if context_dir
            else None
        )
        self.package_root = Path(__file__).resolve().parent / "context"
        self._guide_selection: List[str] = []
        self._guide_selection_reason = ""
        self._guide_selection_revision = 0

    @property
    def default_root(self) -> Path:
        return self.package_root / self.system_name

    def describe_roots(self) -> List[Dict[str, Any]]:
        """Return all configured roots, including missing ones for debugging."""
        roots = []
        if self.context_dir is not None:
            roots.append(
                {
                    "kind": "override",
                    "path": str(self.context_dir),
                    "exists": self.context_dir.exists(),
                }
            )
        roots.append(
            {
                "kind": "default",
                "path": str(self.default_root),
                "exists": self.default_root.exists(),
            }
        )
        return roots

    def roots(self) -> List[tuple]:
        """Return existing roots in precedence order."""
        roots = []
        if self.context_dir is not None and self.context_dir.exists():
            roots.append(("override", self.context_dir))
        if self.default_root.exists():
            roots.append(("default", self.default_root))
        return roots

    def list_files(self) -> List[Dict[str, Any]]:
        """Return the merged context file list."""
        merged = {}
        for kind, root in self.roots():
            for file_path in sorted(root.rglob("*")):
                if not file_path.is_file():
                    continue
                relative_path = file_path.relative_to(root).as_posix()
                if relative_path in merged:
                    continue
                merged[relative_path] = self._describe_file(file_path, root, kind)
        return [merged[path] for path in sorted(merged)]

    def status(self) -> Dict[str, Any]:
        """Return a compact summary of the active context bundle."""
        files = self.list_files()
        available_paths = {item["path"] for item in files}
        preferred_files = {
            "agent-guide.md": "agent-guide.md" in available_paths,
        }
        if self.system_name == "boxmini":
            preferred_files["cartridge.default.json"] = "cartridge.default.json" in available_paths
        return {
            "system": self.system_name,
            "override_dir": str(self.context_dir) if self.context_dir else None,
            "default_dir": str(self.default_root),
            "roots": self.describe_roots(),
            "file_count": len(files),
            "preferred_files": preferred_files,
            "tools": [
                "context_status",
                "list_context_files",
                "read_context_file",
                "select_guide_context",
            ],
            "guide_context": {
                "selected_paths": list(self._guide_selection),
                "reason": self._guide_selection_reason,
                "revision": self._guide_selection_revision,
            },
        }

    def read_text(self, relative_path: str) -> Dict[str, Any]:
        """Read one context file as UTF-8 text."""
        for kind, root in self.roots():
            candidate = self._resolve_relative_path(root, relative_path)
            if candidate.is_file():
                return {
                    "system": self.system_name,
                    "path": candidate.relative_to(root.resolve()).as_posix(),
                    "root": str(root),
                    "source": kind,
                    "content": candidate.read_text(encoding="utf-8"),
                }

        raise FileNotFoundError(
            f"Context file not found for system '{self.system_name}': {relative_path}"
        )

    def select_guide_context(self, paths: List[str], reason: str) -> Dict[str, Any]:
        """Select detailed guide shards and return a host-portable next-turn context update."""
        if not isinstance(paths, list):
            raise ValueError("paths must be a list of guide files.")
        available = {
            str(item["path"])
            for item in self.list_files()
            if self._is_guide_shard(str(item.get("path") or ""))
        }
        selected: List[str] = []
        for item in paths:
            path = str(item or "").strip().replace("\\", "/")
            if path not in available:
                if path == "agent-guide.md":
                    raise ValueError(
                        "agent-guide.md is the pinned operating-guide entrypoint and is loaded "
                        "automatically. Do not select it; select one to five detailed shards such "
                        "as agent-guide/11-temperature.md."
                    )
                raise ValueError(f"Unknown detailed guide file: {path}")
            if path not in selected:
                selected.append(path)
        if not selected:
            raise ValueError("Select at least one detailed guide file.")
        if len(selected) > 5:
            raise ValueError("Select at most five detailed guide files.")

        previous = list(self._guide_selection)
        self._guide_selection = selected
        self._guide_selection_reason = str(reason or "").strip()
        self._guide_selection_revision += 1
        files = [self.read_text(path) for path in selected]
        return {
            "ok": True,
            "system": self.system_name,
            "selected_paths": selected,
            "previous_paths": previous,
            "reason": self._guide_selection_reason,
            "revision": self._guide_selection_revision,
            "context_update": {
                "operation": "replace_detailed_guides",
                "apply_before_next_model_turn": True,
                "paths": selected,
                "files": files,
            },
        }

    @staticmethod
    def _is_guide_shard(path: str) -> bool:
        clean_path = str(path or "").strip().replace("\\", "/")
        return (
            clean_path.startswith("agent-guide/")
            and clean_path.endswith(".md")
            and clean_path != "agent-guide/index.md"
        )

    def _resolve_relative_path(self, root: Path, relative_path: str) -> Path:
        requested = Path(relative_path)
        if requested.is_absolute():
            raise ValueError("Context paths must be relative.")

        candidate = (root / requested).resolve()
        root_resolved = root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError("Context path escapes the context root.") from exc
        return candidate

    def _describe_file(self, file_path: Path, root: Path, kind: str) -> Dict[str, Any]:
        relative_path = file_path.relative_to(root).as_posix()
        return {
            "path": relative_path,
            "source": kind,
            "root": str(root),
            "size_bytes": file_path.stat().st_size,
        }
