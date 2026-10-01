"""Verwandtschaft: gespeicherte Angaben → alle ableitbaren Beziehungen.

Gespeichert werden möglichst einfache Bausteine: Elternteil, Geschwister, Partner.
Alles andere wird daraus abgeleitet – z.B. „Katharina ist meine Schwester“ + „Ulrike ist meine Mutter“
ergibt „Ulrike ist Katharinas Mutter“. Wer eine entferntere Beziehung nennt, ohne den Weg dorthin
(„Gisela ist meine Tante“, aber nicht über welchen Elternteil), dessen Angabe wird wörtlich gespeichert.
"""
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .errors import DomainError


class Gender(StrEnum):
    FEMALE = "w"
    MALE = "m"


class Kin(StrEnum):
    """Wie `person` zu `relative` steht: person ist <Kin> von relative."""
    PARENT = "elternteil"
    CHILD = "kind"
    SIBLING = "geschwister"
    PARTNER = "partner"
    GRANDPARENT = "grosselternteil"
    GRANDCHILD = "enkelkind"
    AUNT_UNCLE = "tante_onkel"
    NIECE_NEPHEW = "nichte_neffe"
    COUSIN = "cousin"
    PARENT_IN_LAW = "schwiegerelternteil"
    CHILD_IN_LAW = "schwiegerkind"
    SIBLING_IN_LAW = "schwager"


INVERSE = {
    Kin.PARENT: Kin.CHILD, Kin.CHILD: Kin.PARENT,
    Kin.GRANDPARENT: Kin.GRANDCHILD, Kin.GRANDCHILD: Kin.GRANDPARENT,
    Kin.AUNT_UNCLE: Kin.NIECE_NEPHEW, Kin.NIECE_NEPHEW: Kin.AUNT_UNCLE,
    Kin.PARENT_IN_LAW: Kin.CHILD_IN_LAW, Kin.CHILD_IN_LAW: Kin.PARENT_IN_LAW,
    Kin.SIBLING: Kin.SIBLING, Kin.PARTNER: Kin.PARTNER, Kin.COUSIN: Kin.COUSIN, Kin.SIBLING_IN_LAW: Kin.SIBLING_IN_LAW,
}
SYMMETRIC = frozenset(k for k, inv in INVERSE.items() if k == inv)

# Bezeichnung je Geschlecht: (weiblich, männlich, unbekannt)
NAMES: dict[Kin, tuple[str, str, str]] = {
    Kin.PARENT: ("Mutter", "Vater", "Elternteil"),
    Kin.CHILD: ("Tochter", "Sohn", "Kind"),
    Kin.SIBLING: ("Schwester", "Bruder", "Geschwister"),
    Kin.PARTNER: ("Partnerin", "Partner", "Partner/in"),
    Kin.GRANDPARENT: ("Großmutter", "Großvater", "Großelternteil"),
    Kin.GRANDCHILD: ("Enkelin", "Enkel", "Enkelkind"),
    Kin.AUNT_UNCLE: ("Tante", "Onkel", "Tante/Onkel"),
    Kin.NIECE_NEPHEW: ("Nichte", "Neffe", "Nichte/Neffe"),
    Kin.COUSIN: ("Cousine", "Cousin", "Cousin/e"),
    Kin.PARENT_IN_LAW: ("Schwiegermutter", "Schwiegervater", "Schwiegerelternteil"),
    Kin.CHILD_IN_LAW: ("Schwiegertochter", "Schwiegersohn", "Schwiegerkind"),
    Kin.SIBLING_IN_LAW: ("Schwägerin", "Schwager", "Schwager/Schwägerin"),
}

F, M = Gender.FEMALE, Gender.MALE
# Wörter, mit denen man jemanden bezeichnet oder anspricht → (Beziehung, Geschlecht)
_WORDS: dict[str, tuple[Kin, Gender | None]] = {
    **{w: (Kin.PARENT, F) for w in ("mama", "mami", "mutti", "mutter")},
    **{w: (Kin.PARENT, M) for w in ("papa", "papi", "vati", "vater")},
    **{w: (Kin.PARENT, None) for w in ("elternteil",)},
    **{w: (Kin.CHILD, F) for w in ("tochter",)},
    **{w: (Kin.CHILD, M) for w in ("sohn",)},
    **{w: (Kin.CHILD, None) for w in ("kind",)},
    **{w: (Kin.SIBLING, F) for w in ("schwester", "schwesterherz")},
    **{w: (Kin.SIBLING, M) for w in ("bruder", "bruderherz")},
    **{w: (Kin.SIBLING, None) for w in ("geschwister", "geschwisterkind")},
    **{w: (Kin.PARTNER, F) for w in ("frau", "ehefrau", "partnerin", "lebensgefährtin", "verlobte")},
    **{w: (Kin.PARTNER, M) for w in ("mann", "ehemann", "partner", "lebensgefährte", "verlobter")},
    **{w: (Kin.GRANDPARENT, F) for w in ("oma", "omi", "großmutter", "grossmutter")},
    **{w: (Kin.GRANDPARENT, M) for w in ("opa", "opi", "großvater", "grossvater")},
    **{w: (Kin.GRANDCHILD, F) for w in ("enkelin", "enkeltochter")},
    **{w: (Kin.GRANDCHILD, M) for w in ("enkel", "enkelsohn")},
    **{w: (Kin.GRANDCHILD, None) for w in ("enkelkind",)},
    **{w: (Kin.AUNT_UNCLE, F) for w in ("tante",)},
    **{w: (Kin.AUNT_UNCLE, M) for w in ("onkel",)},
    **{w: (Kin.NIECE_NEPHEW, F) for w in ("nichte",)},
    **{w: (Kin.NIECE_NEPHEW, M) for w in ("neffe",)},
    **{w: (Kin.COUSIN, F) for w in ("cousine", "kusine")},
    **{w: (Kin.COUSIN, M) for w in ("cousin",)},
    **{w: (Kin.PARENT_IN_LAW, F) for w in ("schwiegermutter", "schwiegermama")},
    **{w: (Kin.PARENT_IN_LAW, M) for w in ("schwiegervater", "schwiegerpapa")},
    **{w: (Kin.CHILD_IN_LAW, F) for w in ("schwiegertochter",)},
    **{w: (Kin.CHILD_IN_LAW, M) for w in ("schwiegersohn",)},
    **{w: (Kin.SIBLING_IN_LAW, F) for w in ("schwägerin", "schwaegerin")},
    **{w: (Kin.SIBLING_IN_LAW, M) for w in ("schwager",)},
}
_POSSESSIVE = ("meine ", "meiner ", "meinem ", "meinen ", "mein ")


@dataclass(frozen=True)
class KinTerm:
    kin: Kin
    gender: Gender | None


def parse_term(word: str) -> KinTerm | None:
    """„Mama“, „meine Schwester“, „Schwiegermutter“ … → Beziehung + Geschlecht. None = kein Verwandtschaftswort."""
    w = " ".join(word.lower().split())
    for prefix in _POSSESSIVE:
        w = w.removeprefix(prefix)
    found = _WORDS.get(w)
    return KinTerm(*found) if found else None


def require_term(word: str) -> KinTerm:
    if term := parse_term(word):
        return term
    raise DomainError(f"„{word}“ kenne ich nicht als Verwandtschaft. Möglich sind z.B. Mutter, Vater, Schwester, "
                      "Bruder, Tochter, Sohn, Partner/in, Oma, Opa, Tante, Onkel, Cousine, Cousin, Schwiegermutter, "
                      "Schwager.")


def name_of(kin: Kin, gender: Gender | None) -> str:
    female, male, neutral = NAMES[kin]
    return female if gender == F else male if gender == M else neutral


@dataclass(frozen=True)
class Fact:
    """Gespeicherte Angabe: person ist <kin> von relative."""
    person: int
    relative: int
    kin: Kin

    def normalized(self) -> "Fact":
        """Eine Richtung je Beziehung: Kind → Elternteil, symmetrische mit kleinerer id zuerst."""
        if self.kin in SYMMETRIC:
            return Fact(min(self.person, self.relative), max(self.person, self.relative), self.kin)
        if self.kin in (Kin.CHILD, Kin.GRANDCHILD, Kin.NIECE_NEPHEW, Kin.CHILD_IN_LAW):
            return Fact(self.relative, self.person, INVERSE[self.kin])
        return self


class FamilyTree:
    """Alle Beziehungen, die sich aus den gespeicherten Angaben ergeben."""

    def __init__(self, facts: Iterable[Fact]):
        self._facts = [f.normalized() for f in facts]
        self._relations: dict[int, dict[int, set[Kin]]] = defaultdict(lambda: defaultdict(set))
        self._derive()

    def relations(self, person: int) -> dict[int, set[Kin]]:
        """{Verwandte/r: {wie er/sie zu `person` steht}} – z.B. {Ulrike: {PARENT}} für Timmo."""
        return {other: set(kins) for other, kins in self._relations.get(person, {}).items() if kins}

    def kins(self, person: int, relative: int) -> set[Kin]:
        """Wie `person` zu `relative` steht."""
        return set(self._relations.get(relative, {}).get(person, ()))

    # --- Ableitung ---

    def _derive(self) -> None:
        parents, partners, stated = defaultdict(set), defaultdict(set), []
        sibling_links = []
        for f in self._facts:
            if f.kin == Kin.PARENT:
                parents[f.relative].add(f.person)
            elif f.kin == Kin.PARTNER:
                partners[f.person].add(f.relative)
                partners[f.relative].add(f.person)
            elif f.kin == Kin.SIBLING:
                sibling_links.append((f.person, f.relative))
            else:
                stated.append(f)

        group = self._sibling_groups(sibling_links, parents)
        # Geschwister teilen ihre Eltern
        all_parents = {p: set().union(*(parents[s] for s in group[p])) for p in group}
        people = set(group) | set(partners) | {f.person for f in stated} | {f.relative for f in stated}
        people |= {p for ps in all_parents.values() for p in ps}

        def parents_of(x): return all_parents.get(x, set())
        def siblings_of(x): return group.get(x, {x}) - {x}

        for x in people:
            for p in parents_of(x):
                self._add(p, x, Kin.PARENT)
                for g in parents_of(p):
                    self._add(g, x, Kin.GRANDPARENT)
                for a in siblings_of(p):
                    self._add(a, x, Kin.AUNT_UNCLE)
                    for c in self._children(a, all_parents):
                        self._add(c, x, Kin.COUSIN)
                    for ap in partners.get(a, ()):
                        self._add(ap, x, Kin.AUNT_UNCLE)
            for s in siblings_of(x):
                self._add(s, x, Kin.SIBLING)
                for sp in partners.get(s, ()):
                    self._add(sp, x, Kin.SIBLING_IN_LAW)
            for partner in partners.get(x, ()):
                self._add(partner, x, Kin.PARTNER)
                for pil in parents_of(partner):
                    self._add(pil, x, Kin.PARENT_IN_LAW)
                for sil in siblings_of(partner):
                    self._add(sil, x, Kin.SIBLING_IN_LAW)
        for f in stated:
            self._add(f.person, f.relative, f.kin)

    @staticmethod
    def _children(person: int, all_parents: dict[int, set[int]]) -> set[int]:
        return {child for child, ps in all_parents.items() if person in ps}

    @staticmethod
    def _sibling_groups(links: list[tuple[int, int]], parents: dict[int, set[int]]) -> dict[int, set[int]]:
        """Geschwister-Gruppen: direkt genannte Geschwister und Kinder desselben Elternteils, transitiv."""
        root: dict[int, int] = {}

        def find(x):
            root.setdefault(x, x)
            while root[x] != x:
                root[x] = root[root[x]]
                x = root[x]
            return x

        def union(a, b): root[find(a)] = find(b)

        for a, b in links:
            union(a, b)
        by_parent = defaultdict(list)
        for child, ps in parents.items():
            find(child)
            for p in ps:
                by_parent[p].append(child)
        for children in by_parent.values():
            for c in children[1:]:
                union(children[0], c)
        groups = defaultdict(set)
        for x in list(root):
            groups[find(x)].add(x)
        return {x: groups[find(x)] for x in root}

    def _add(self, person: int, relative: int, kin: Kin) -> None:
        if person == relative:
            return
        self._relations[relative][person].add(kin)
        self._relations[person][relative].add(INVERSE[kin])
