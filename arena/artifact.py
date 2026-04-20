from __future__ import annotations

import os
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactChunk:
    path: str
    content: str
    truncated: bool


class ArtifactStore:
    def __init__(
        self,
        *,
        workspace_root: str,
        artifact_paths: list[str],
        max_chars_per_file: int = 40_000,
    ):
        self._root = Path(workspace_root).resolve()
        self._paths = [self._normalize(p) for p in artifact_paths]
        self._max_chars = max_chars_per_file
        self._cache: dict[str, ArtifactChunk] = {}

    def _normalize(self, p: str) -> str:
        pp = Path(p)
        if not pp.is_absolute():
            pp = (self._root / pp).resolve()
        else:
            pp = pp.resolve()
        try:
            pp.relative_to(self._root)
        except Exception as e:
            raise ValueError(f"Artifact path must be inside workspace: {pp}") from e
        return str(pp)

    @property
    def artifact_paths(self) -> list[str]:
        return list(self._paths)

    def read_artifacts(self) -> list[ArtifactChunk]:
        return [self.read_path(p) for p in self._paths]

    def read_path(self, path: str) -> ArtifactChunk:
        norm = self._normalize(path)
        if norm in self._cache:
            return self._cache[norm]
        p = Path(norm)
        if not p.exists():
            raise FileNotFoundError(norm)
        
        # Branch on extension
        if p.suffix.lower() == ".docx":
            data = self._read_docx(norm)
        else:
            data = p.read_text(encoding="utf-8", errors="replace")

        truncated = False
        if len(data) > self._max_chars:
            data = data[: self._max_chars] + "\n\n...[TRUNCATED]..."
            truncated = True
        chunk = ArtifactChunk(path=norm, content=data, truncated=truncated)
        self._cache[norm] = chunk
        return chunk

    def _read_docx(self, path: str) -> str:
        """Dependency-free extraction of text from .docx (Word) files."""
        try:
            with zipfile.ZipFile(path) as zf:
                # Word stores the main body in word/document.xml
                xml_content = zf.read("word/document.xml")
                tree = ET.fromstring(xml_content)
                
                # Namespaces for Word XML
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                
                # Extract all text from <w:t> tags
                return "".join([node.text for node in tree.findall('.//w:t', ns) if node.text])
        except Exception as e:
            return f"[ERROR: Could not parse .docx file at {path}: {e}]"

    def summarize_for_prompt(self) -> str:
        """Small-ish summary header for system/user prompts."""
        lines = ["ARTIFACT_FILES:"]
        for p in self._paths:
            rel = str(Path(p).relative_to(self._root))
            lines.append(f"- {rel}")
        return "\n".join(lines)


def workspace_root() -> str:
    return os.getcwd()

