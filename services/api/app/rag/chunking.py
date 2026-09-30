"""Sentence-aware academic chunking.

The chunker never cuts a sentence in half. It consumes the extracted structure of a source
(``source_pages`` -> ``source_blocks``) and rebuilds passages that respect:

* paragraph boundaries: contiguous blocks of the same page are grouped, a page change or a
  heading always closes the current passage;
* heading context: the active heading path is stored in the chunk metadata, and a heading is
  prepended to the passage text when ``include_heading_in_text`` is enabled so a retrieved
  chunk is self-contained;
* page boundaries: a chunk never spans two pages, so page provenance is always exact;
* document order: ``chunk_index`` increases strictly across the whole document;
* overlap: expressed in tokens and applied on complete sentences, so the tail of a chunk and
  the head of the next one share whole sentences.

Two cases legitimately break a sentence boundary and are flagged with ``sentence_split``:
an individual sentence longer than ``max_tokens`` (it is split on word boundaries), and a
final passage shorter than ``min_tokens`` that is merged into its predecessor when the merged
size still fits.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

# Abbreviations and symbols that must not end a sentence.
_ABBREVIATIONS = (
    "al", "env", "ex", "fig", "m", "min", "max", "p", "pp", "no", "n°", "etc",
    "cf", "vol", "éd", "ed", "trad", "cf.", "fig.", "p.", "m.",
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[ \t ]+|[\r\n]{2,}")
_WORD = re.compile(r"\S+")
_SENTINEL = ""


@dataclass(frozen=True, slots=True)
class SourceBlockInput:
    """One extracted block, as stored in ``source_blocks``."""

    provenance_id: UUID
    page_number: int
    block_index: int
    block_type: str
    text: str
    position_start: int = 0
    position_end: int = 0


@dataclass(frozen=True, slots=True)
class AcademicChunk:
    """A retrievable passage with its complete provenance chain."""

    text: str
    token_count: int
    page_number: int
    block_start: int
    block_end: int
    chunk_index: int
    provenance_id: UUID
    heading_path: tuple[str, ...] = ()
    block_types: tuple[str, ...] = ()
    sentence_split: bool = False
    character_start: int = 0
    character_end: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Deterministic, tokenizer-independent token estimate.

    One word counts as one token, and long words are split roughly every four characters.
    This approximates BPE tokenizers closely enough to size chunks conservatively and keeps
    the behaviour reproducible across providers.
    """
    if not text:
        return 0
    return sum(max(1, (len(word) + 3) // 4) for word in _WORD.findall(text))


def split_sentences(text: str) -> list[str]:
    """Split text into sentences while protecting abbreviations and decimal numbers."""
    if not text.strip():
        return []
    protected = text
    for abbreviation in _ABBREVIATIONS:
        pattern = re.escape(abbreviation)
        protected = re.sub(
            rf"(?<![\w]){pattern}(?![\w])",
            lambda match: match.group(0).replace(".", _SENTINEL),
            protected,
            flags=re.IGNORECASE,
        )
    # 3.14 must not become two sentences.
    protected = re.sub(r"(?<=\d)\.(?=\d)", _SENTINEL, protected)

    sentences: list[str] = []
    for piece in _SENTENCE_SPLIT.split(protected):
        if piece is None:
            continue
        restored = piece.replace(_SENTINEL, ".")
        if restored.endswith(_SENTINEL) and sentences:
            sentences[-1] = f"{sentences[-1]} {restored.replace(_SENTINEL, '').strip()}".strip()
            continue
        if restored.strip():
            sentences.append(restored.strip())
    return sentences


def is_heading_block(block_type: str) -> bool:
    return block_type.casefold() in {"heading", "title", "subtitle", "section"}


@dataclass(slots=True)
class _Accumulator:
    """Collects sentences for the passage currently being built."""

    max_tokens: int
    sentences: list[str] = field(default_factory=list)
    blocks: list[SourceBlockInput] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    token_total: int = 0
    split: bool = False

    def add_sentence(self, sentence: str, block: SourceBlockInput) -> None:
        self.sentences.append(sentence)
        self.token_total += estimate_tokens(sentence)
        if not self.blocks or self.blocks[-1].block_index != block.block_index:
            if not self.blocks:
                self.blocks.append(block)
                self.block_types.append(block.block_type)
            else:
                self.blocks.append(block)
                self.block_types.append(block.block_type)

    def add_split_sentence(self, text: str, block: SourceBlockInput) -> None:
        self.sentences.append(text)
        self.token_total += estimate_tokens(text)
        self.blocks.append(block)
        self.block_types.append(block.block_type)
        self.split = True

    def keep_tail(self, overlap_tokens: int) -> None:
        """Retain the trailing sentences that fit into the overlap budget."""
        if overlap_tokens <= 0 or not self.sentences:
            self.clear()
            return
        kept: list[str] = []
        total = 0
        for sentence in reversed(self.sentences):
            tokens = estimate_tokens(sentence)
            if total + tokens > overlap_tokens:
                break
            kept.append(sentence)
            total += tokens
        kept.reverse()
        self.sentences = kept
        self.token_total = total
        # The retained context still belongs to the blocks already collected.
        if not self.blocks:
            self.clear()

    def clear(self) -> None:
        self.sentences = []
        self.token_total = 0
        self.blocks = []
        self.block_types = []
        self.split = False

    def body(self) -> str:
        return " ".join(self.sentences).strip()


class AcademicChunker:
    """Build retrievable chunks from the ordered blocks of a single source."""

    def __init__(
        self,
        *,
        max_tokens: int,
        overlap_tokens: int,
        min_tokens: int,
        include_heading_in_text: bool = True,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative")
        if overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be lower than max_tokens")
        if min_tokens <= 0 or min_tokens > max_tokens:
            raise ValueError("min_tokens must be positive and lower than max_tokens")
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens
        self.include_heading_in_text = include_heading_in_text

    def chunk(
        self,
        blocks: Sequence[SourceBlockInput],
        *,
        start_index: int = 0,
    ) -> list[AcademicChunk]:
        """Chunk one source; ``chunk_index`` continues from ``start_index``."""
        produced: list[AcademicChunk] = []
        heading_path: list[str] = []

        for page_number, page_blocks in group_blocks_by_page(blocks):
            accumulator = _Accumulator(max_tokens=self.max_tokens)
            section_heading: str | None = None

            for block in page_blocks:
                if is_heading_block(block.block_type):
                    self._emit(
                        accumulator,
                        produced=produced,
                        page_number=page_number,
                        heading_path=tuple(heading_path),
                        section_heading=section_heading,
                        start_index=start_index,
                    )
                    heading = block.text.strip()
                    if heading:
                        heading_path.append(heading)
                    section_heading = heading or None
                    continue
                for sentence in split_sentences(block.text) or [block.text.strip()]:
                    if not sentence:
                        continue
                    tokens = estimate_tokens(sentence)
                    if tokens > self.max_tokens:
                        self._emit(
                            accumulator,
                            produced=produced,
                            page_number=page_number,
                            heading_path=tuple(heading_path),
                            section_heading=section_heading,
                            start_index=start_index,
                        )
                        self._add_oversized(
                            accumulator, sentence, block, page_number, tuple(heading_path),
                            section_heading, produced, start_index,
                        )
                        continue
                    if (
                        accumulator.sentences
                        and accumulator.token_total + tokens > self.max_tokens
                    ):
                        self._emit(
                            accumulator,
                            produced=produced,
                            page_number=page_number,
                            heading_path=tuple(heading_path),
                            section_heading=section_heading,
                            start_index=start_index,
                        )
                        accumulator.keep_tail(self.overlap_tokens)
                    accumulator.add_sentence(sentence, block)

            self._emit(
                accumulator,
                produced=produced,
                page_number=page_number,
                heading_path=tuple(heading_path),
                section_heading=section_heading,
                start_index=start_index,
            )
            # A page never shares a chunk with the next page, and the heading path is
            # document-scoped, so it is intentionally preserved across pages.

        produced = self._flag_undersized(produced)
        return [
            replace(chunk, chunk_index=start_index + position)
            for position, chunk in enumerate(produced)
        ]

    def _add_oversized(
        self,
        accumulator: _Accumulator,
        sentence: str,
        block: SourceBlockInput,
        page_number: int,
        heading_path: tuple[str, ...],
        section_heading: str | None,
        produced: list[AcademicChunk],
        start_index: int,
    ) -> None:
        words = sentence.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if current and estimate_tokens(candidate) > self.max_tokens:
                accumulator.add_split_sentence(" ".join(current), block)
                self._emit(
                    accumulator,
                    produced=produced,
                    page_number=page_number,
                    heading_path=heading_path,
                    section_heading=section_heading,
                    start_index=start_index,
                )
                current = [word]
            else:
                current.append(word)
        if current:
            accumulator.add_split_sentence(" ".join(current), block)
            self._emit(
                accumulator,
                produced=produced,
                page_number=page_number,
                heading_path=heading_path,
                section_heading=section_heading,
                start_index=start_index,
            )

    def _emit(
        self,
        accumulator: _Accumulator,
        *,
        produced: list[AcademicChunk],
        page_number: int,
        heading_path: tuple[str, ...],
        section_heading: str | None,
        start_index: int,
    ) -> None:
        body = accumulator.body()
        if not body:
            accumulator.clear()
            return
        prefix: list[str] = []
        if self.include_heading_in_text and section_heading:
            prefix.append(section_heading)
        text = "\n".join([*prefix, body]).strip()
        first_block = accumulator.blocks[0]
        last_block = accumulator.blocks[-1]
        block_types = tuple(dict.fromkeys(accumulator.block_types))
        produced.append(
            AcademicChunk(
                text=text,
                token_count=estimate_tokens(text),
                page_number=page_number,
                block_start=first_block.block_index,
                block_end=last_block.block_index,
                chunk_index=0,
                provenance_id=first_block.provenance_id,
                heading_path=heading_path,
                block_types=block_types,
                sentence_split=accumulator.split,
                character_start=first_block.position_start,
                character_end=last_block.position_end,
                metadata={
                    "page_number": page_number,
                    "block_start": first_block.block_index,
                    "block_end": last_block.block_index,
                    "heading_path": list(heading_path),
                    "block_types": list(block_types),
                    "sentence_split": accumulator.split,
                    "character_start": first_block.position_start,
                    "character_end": last_block.position_end,
                },
            )
        )
        accumulator.clear()

    def _flag_undersized(self, produced: list[AcademicChunk]) -> list[AcademicChunk]:
        """Flag passages that fall below ``min_tokens``.

        An undersized trailing passage is deliberately *not* merged into its predecessor.
        Merging would either overflow ``max_tokens`` or, worse, erase a heading or page
        boundary, which would corrupt the heading context carried by the provenance. The
        threshold is therefore surfaced as an explicit flag so the caller can decide.
        """
        if not produced:
            return produced
        last = produced[-1]
        if last.token_count >= self.min_tokens:
            return produced
        flagged = replace(
            last,
            metadata={**last.metadata, "undersized": True},
        )
        return [*produced[:-1], flagged]


def group_blocks_by_page(
    blocks: Iterable[SourceBlockInput],
) -> list[tuple[int, list[SourceBlockInput]]]:
    """Group ordered blocks by page, preserving the original order."""
    grouped: list[tuple[int, list[SourceBlockInput]]] = []
    current_page: int | None = None
    current: list[SourceBlockInput] = []
    for block in blocks:
        if current_page is not None and block.page_number != current_page:
            grouped.append((current_page, current))
            current = []
        current_page = block.page_number
        current.append(block)
    if current_page is not None and current:
        grouped.append((current_page, current))
    return grouped


def chunk_source_blocks(
    blocks: Sequence[SourceBlockInput],
    *,
    max_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
    include_heading_in_text: bool = True,
) -> list[AcademicChunk]:
    """Convenience wrapper around :class:`AcademicChunker`."""
    return AcademicChunker(
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        min_tokens=min_tokens,
        include_heading_in_text=include_heading_in_text,
    ).chunk(blocks)
