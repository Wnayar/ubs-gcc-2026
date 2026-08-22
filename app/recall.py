"""Retrieval over the tool-box study materials (sheet 2, "Problem Set 1: Exam Time").

The android asks a question, we hand back *passages* and it writes its own
answer from them. Two facts shape everything here:

* The budget is **900 `o200k_base` tokens summed over the list we return**, and
  the corpus is 9,418 tokens. We can afford roughly a third of one document,
  and there is no reward for coming in under budget — so the packer fills it.
* The corpus is written to punish careless retrieval. Nearly every fact ships
  with a decoy in the same paragraph: the Kesterline array (14 March) beside
  the Halberd sub-array (12 March), the main habitat at 6,214 m beside the
  annex at 6,050 m, call sign Umbral Seven beside the backup Umbral Two. So a
  passage is a whole paragraph wherever it fits — the sentence that
  disambiguates is the one next to the answer, and shipping the fact without it
  is how the android confidently answers with the decoy.

No tokeniser runs here. Every string we can emit had its exact count baked into
`data/study_materials.json` by `tools/fetch_study_materials.py`, and we never
concatenate two of them, so the running total is an exact integer sum.
"""
import json
import math
import pathlib
import re

BUDGET = 900

DATA = pathlib.Path(__file__).resolve().parent / "data" / "study_materials.json"

WORD = re.compile(r"[a-z0-9_]+")
STOP_CODE = re.compile(r"stop[_\s-]?0*(\d{1,2})")

STOPWORDS = frozenset(
    """a an the and or but if then than that this these those there here of in on at to from by
    for with without about into over under again further is are was were be been being am do does
    did doing have has had having i you he she it we they them his her its their my your our what
    which who whom whose when where why how all any both each few more most other some such no nor
    not only own same so too very can will just should now does did as it's what's tell me give
    show find know say said says please would could may might must one""".split()
)

# Light suffix stripping so "recalibrated" and "calibration" land on one stem.
# Deliberately blunt: exact matches carry the ranking, this only widens recall.
SUFFIXES = (
    ("ational", "at"), ("ations", "at"), ("ation", "at"),
    ("izations", "iz"), ("ization", "iz"),
    ("ements", ""), ("ement", ""), ("ments", ""), ("ment", ""),
    ("ness", ""), ("ities", "ity"), ("ity", ""),
    ("ies", "y"), ("ing", ""), ("edly", ""), ("ed", ""), ("ly", ""),
    ("es", ""), ("s", ""), ("e", ""),
)


def stem(word: str) -> str:
    if word.startswith("re") and len(word) > 6:
        word = word[2:]
    for suffix, replacement in SUFFIXES:
        if word.endswith(suffix):
            trimmed = word[: -len(suffix)] + replacement
            if len(trimmed) >= 4:
                return trimmed
    return word


def terms(text: str) -> list[str]:
    """Words worth matching on, each paired with its stem by the caller."""
    return [w for w in WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def _keys(text: str) -> list[str]:
    out: list[str] = []
    for word in terms(text):
        out.append(word)
        root = stem(word)
        if root != word:
            out.append(root)
    return out


# A question need not share a single word with its answer. The statement's own
# worked example asks when the "sensor grid" was "brought back into alignment"
# and the answer is that the Kesterline *array* was *recalibrated* on 14 March —
# "sensor", "grid" and "alignment" appear nowhere in that document, so a
# lexical scorer routes it to the wrong document and returns 900 useless tokens.
#
# This bridges the everyday word to the vocabulary these five documents use. It
# is written against the corpus, which is fixed and public, and it only ever
# *adds* candidate terms at reduced weight — a real word match always outranks
# an inferred one, so a wrong guess here costs ranking, never correctness.
EXPANSIONS = {
    # instruments and measurement
    "sensor": ("hydrophone", "array", "acoustic"),
    "grid": ("array", "ring", "network"),
    "detector": ("hydrophone", "array", "acoustic"),
    "instrument": ("hydrophone", "array", "profiler"),
    "align": ("calibrat", "recalibrat", "acoustic", "array"),
    "alignment": ("calibrat", "recalibrat", "acoustic", "array"),
    "tune": ("calibrat", "torque", "adjust"),
    "adjust": ("calibrat", "torque", "amend"),
    "tighten": ("torque", "gasket", "newton"),
    "tight": ("torque", "gasket", "newton"),
    # places, depth, structure
    "deep": ("depth", "meter", "habitat", "abyssal"),
    "depth": ("meter", "habitat", "abyssal"),
    "stop": ("marker", "berth", "platform", "register"),
    "marker": ("stop", "berth", "register"),
    "platform": ("stop", "marker", "line"),
    # people
    "boss": ("director", "lead", "chair"),
    "head": ("director", "lead", "chair"),
    "crew": ("scientist", "technician", "occupancy", "staff"),
    "people": ("scientist", "technician", "occupancy", "crew", "member"),
    "population": ("occupancy", "resident", "crew"),
    "headcount": ("occupancy", "resident", "crew"),
    # schedules and events
    "often": ("cycle", "every", "schedule", "cadence"),
    "delivery": ("resupply", "provision", "vessel", "consignment"),
    "restock": ("resupply", "provision"),
    "breakdown": ("failure", "fault", "incident"),
    "broke": ("failure", "fault", "incident"),
    "outage": ("failure", "incident"),
    # domain vocabulary of the five documents
    "sub": ("submersible", "craft"),
    "submarine": ("submersible", "craft"),
    "medication": ("dose", "dosing", "milligram", "product"),
    "drug": ("dose", "dosing", "milligram", "investigational"),
    "bloodwork": ("enzyme", "laboratory", "bloodwork"),
    "build": ("release", "version", "pipeline"),
    "version": ("release",),
    "memory": ("megabyte", "texture", "budget"),
    "framerate": ("millisecond", "frame", "render"),
    "fridge": ("refrigerat", "cold", "storage"),
    "chiller": ("refrigerat", "cold", "storage"),
    "scales": ("weighbridge", "consignment"),
    "callsign": ("call", "sign", "umbral", "radio"),
}

EXPANSION_WEIGHT = 0.45


def query_weights(question: str) -> dict[str, float]:
    """Query keys -> weight. Words the asker used count for more than words we
    inferred on their behalf."""
    weights: dict[str, float] = {}
    for word in terms(question):
        for key in (word, stem(word)):
            weights[key] = max(weights.get(key, 0.0), 1.0)
        for extra in EXPANSIONS.get(word, ()) + EXPANSIONS.get(stem(word), ()):
            for key in (extra, stem(extra)):
                weights.setdefault(key, EXPANSION_WEIGHT)
    return weights


class Passage:
    """One string we may emit, with the exact token count of that string."""

    __slots__ = ("text", "tokens", "doc", "section", "para", "kind", "keys")

    def __init__(self, text, tokens, doc, section, para, kind):
        self.text = text
        self.tokens = tokens
        self.doc = doc
        self.section = section
        self.para = para
        self.kind = kind  # "paragraph" or "sentence"
        self.keys = _keys(text)


class Corpus:
    def __init__(self, payload: dict):
        self.documents = payload["documents"]
        self.paragraphs: list[Passage] = []
        self.sentences: list[Passage] = []
        # heading/header units, keyed so the packer can charge for them once
        self.headers: dict[int, dict] = {}
        self.headings: dict[tuple[int, int], dict] = {}
        self.doc_keys: dict[int, list[str]] = {}

        for document in self.documents:
            doc_id = document["id"]
            self.headers[doc_id] = document["header"]
            words: list[str] = _keys(document["title"])
            for s_index, section in enumerate(document["sections"]):
                self.headings[(doc_id, s_index)] = section["heading"]
                words += _keys(section["heading"]["text"])
                for p_index, paragraph in enumerate(section["paragraphs"]):
                    passage = Passage(
                        paragraph["text"], paragraph["tokens"], doc_id, s_index, p_index,
                        "paragraph",
                    )
                    self.paragraphs.append(passage)
                    words += passage.keys
                    for sentence in paragraph["sentences"]:
                        self.sentences.append(
                            Passage(sentence["text"], sentence["tokens"], doc_id,
                                    s_index, p_index, "sentence")
                        )
            self.doc_keys[doc_id] = words

        self._index(self.paragraphs)

    def _index(self, passages: list[Passage]) -> None:
        """BM25 statistics over paragraphs — the unit we actually rank."""
        self.frequency: dict[str, int] = {}
        for passage in passages:
            for key in set(passage.keys):
                self.frequency[key] = self.frequency.get(key, 0) + 1
        self.count = len(passages)
        self.average_length = sum(len(p.keys) for p in passages) / max(self.count, 1)

        self.doc_frequency: dict[str, int] = {}
        for words in self.doc_keys.values():
            for key in set(words):
                self.doc_frequency[key] = self.doc_frequency.get(key, 0) + 1

    # --- scoring -----------------------------------------------------------

    def _idf(self, key: str, frequency: dict[str, int], total: int) -> float:
        seen = frequency.get(key, 0)
        if not seen:
            return 0.0
        return math.log(1 + (total - seen + 0.5) / (seen + 0.5))

    def score(self, query: dict[str, float], passage: Passage) -> float:
        if not query:
            return 0.0
        counts: dict[str, int] = {}
        for key in passage.keys:
            counts[key] = counts.get(key, 0) + 1
        length = len(passage.keys) or 1
        total = 0.0
        for key, weight in query.items():
            found = counts.get(key, 0)
            if not found:
                continue
            idf = self._idf(key, self.frequency, self.count)
            total += weight * idf * (found * 2.5) / (
                found + 1.5 * (0.25 + 0.75 * length / self.average_length)
            )
        return total

    def document_scores(self, query: dict[str, float]) -> dict[int, float]:
        """Which document the question is about — the decision that matters most.

        Judged on the whole document as one bag of words rather than on its best
        paragraph: evidence for "this is the transit authority" is spread across
        the document, and a single lucky paragraph elsewhere should not outvote it.
        """
        scores: dict[int, float] = {}
        for doc_id, words in self.doc_keys.items():
            counts: dict[str, int] = {}
            for key in words:
                counts[key] = counts.get(key, 0) + 1
            total = 0.0
            for key, weight in query.items():
                found = counts.get(key, 0)
                if found:
                    total += weight * self._idf(
                        key, self.doc_frequency, len(self.doc_keys)
                    ) * (1 + math.log(found))
            scores[doc_id] = total
        return scores


def _load() -> Corpus:
    return Corpus(json.loads(DATA.read_text()))


CORPUS = _load()


# --- STOP_xx lookup --------------------------------------------------------

def _stop_sentences() -> list[tuple[str, Passage]]:
    found = []
    for passage in CORPUS.sentences:
        match = re.search(r"STOP_(\d+)", passage.text)
        if match:
            found.append((f"STOP_{int(match.group(1)):02d}", passage))
    return found


STOP_SENTENCES = _stop_sentences()


def resolve_location(name: str) -> str | None:
    """A place name from the study materials -> the map marker that serves it.

    Part 3 turns on this: the destination is given as a place ("Marrowgate
    Market") and the map only knows STOP_07. Getting it wrong is, in the
    statement's own words, "the likeliest way to lose the points".
    """
    if not name or not name.strip():
        return None
    direct = STOP_CODE.search(name.lower())
    if direct:
        return f"STOP_{int(direct.group(1)):02d}"

    wanted = set(_keys(name))
    if not wanted:
        return None
    best, best_score = None, 0.0
    for code, passage in STOP_SENTENCES:
        overlap = wanted & set(passage.keys)
        if not overlap:
            continue
        # rare words carry the identity of a place; "the centre" does not
        score = sum(CORPUS._idf(key, CORPUS.frequency, CORPUS.count) for key in overlap)
        score /= math.sqrt(len(wanted))
        if score > best_score:
            best, best_score = code, score
    return best if best_score >= 1.0 else None


def known_locations() -> list[tuple[str, str]]:
    """(code, the sentence that names it) for every marker in the materials."""
    return [(code, passage.text) for code, passage in sorted(STOP_SENTENCES)]


# --- packing ---------------------------------------------------------------

FACT = re.compile(r"\d|STOP_\d+")


def _fact_bearing(passage: Passage) -> bool:
    """A sentence worth spending leftover budget on.

    The questions are about dates, counts, limits, codes and names, so a
    sentence carrying a number or a proper noun is worth several times its
    length in prose that only sets the scene.
    """
    if FACT.search(passage.text):
        return True
    capitals = re.findall(r"\b[A-Z][a-z]{2,}", passage.text)
    return len(capitals) >= 2


class _Packer:
    """Greedy fill of the 900 tokens, charging for headers/headings once."""

    def __init__(self, budget: int):
        self.budget = budget
        self.used = 0
        self.docs: set[int] = set()
        self.sections: set[tuple[int, int]] = set()
        self.chosen: dict[tuple[int, int], list[Passage]] = {}
        self.taken: set[tuple[int, int, int, str]] = set()

    def _overhead(self, passage: Passage) -> int:
        cost = 0
        if passage.doc not in self.docs:
            cost += CORPUS.headers[passage.doc]["tokens"]
        if (passage.doc, passage.section) not in self.sections:
            cost += CORPUS.headings[(passage.doc, passage.section)]["tokens"]
        return cost

    def add(self, passage: Passage) -> bool:
        key = (passage.doc, passage.section, passage.para, passage.kind)
        if key in self.taken:
            return False
        cost = passage.tokens + self._overhead(passage)
        if self.used + cost > self.budget:
            return False
        self.used += cost
        self.docs.add(passage.doc)
        self.sections.add((passage.doc, passage.section))
        self.chosen.setdefault((passage.doc, passage.section), []).append(passage)
        self.taken.add(key)
        return True

    def covered(self, passage: Passage) -> bool:
        """True if this paragraph is already in the answer, whole."""
        return (passage.doc, passage.section, passage.para, "paragraph") in self.taken

    def emit(self, order: list[int]) -> list[str]:
        out: list[str] = []
        for doc_id in order:
            if doc_id not in self.docs:
                continue
            document = next(d for d in CORPUS.documents if d["id"] == doc_id)
            out.append(CORPUS.headers[doc_id]["text"])
            for s_index, section in enumerate(document["sections"]):
                picked = self.chosen.get((doc_id, s_index))
                if not picked:
                    continue
                out.append(section["heading"]["text"])
                for passage in sorted(picked, key=lambda p: (p.para, p.kind == "sentence")):
                    out.append(passage.text)
        return out


def recall(question: str, budget: int = BUDGET) -> list[str]:
    """Passages from the study materials most likely to carry the answer."""
    query = query_weights(question or "")
    packer = _Packer(budget)

    if not query:
        # Nothing to go on: one paragraph of context from each document beats
        # an empty answer, and the android can ask again with better words.
        for document in CORPUS.documents:
            for passage in CORPUS.paragraphs:
                if passage.doc == document["id"]:
                    packer.add(passage)
                    break
        return packer.emit([d["id"] for d in CORPUS.documents])

    scored = sorted(
        ((CORPUS.score(query, p), p) for p in CORPUS.paragraphs),
        key=lambda pair: (-pair[0], pair[1].doc, pair[1].section, pair[1].para),
    )
    documents = CORPUS.document_scores(query)
    ranked_docs = sorted(documents, key=lambda d: -documents[d])
    winner = ranked_docs[0]

    # The single best paragraph anywhere goes in first even if it sits outside
    # the winning document — when routing is wrong, this is the one thing that
    # still rescues the answer.
    if scored and scored[0][0] > 0:
        packer.add(scored[0][1])

    # Then the winning document, best paragraphs first.
    for score, passage in scored:
        if passage.doc == winner and score > 0:
            packer.add(passage)

    # Leftover budget: fact-bearing sentences from the winner's paragraphs that
    # did not fit whole. Dates, counts and codes are what gets asked.
    for passage in CORPUS.sentences:
        if passage.doc != winner or packer.covered(passage):
            continue
        if _fact_bearing(passage):
            packer.add(passage)

    # Still short: the runner-up document's best paragraphs, then anything left
    # in the winner. Coming in under 900 buys nothing.
    for score, passage in scored:
        if score > 0 and passage.doc != winner:
            packer.add(passage)
    for score, passage in scored:
        if passage.doc == winner:
            packer.add(passage)

    order = [winner] + [d for d in ranked_docs if d != winner]
    return packer.emit(order)


def token_total(passages: list[str]) -> int:
    """Exact o200k_base total for passages we emitted, from the baked counts."""
    sizes: dict[str, int] = {}
    for doc_id, header in CORPUS.headers.items():
        sizes[header["text"]] = header["tokens"]
    for heading in CORPUS.headings.values():
        sizes[heading["text"]] = heading["tokens"]
    for passage in CORPUS.paragraphs + CORPUS.sentences:
        sizes[passage.text] = passage.tokens
    return sum(sizes[text] for text in passages)
