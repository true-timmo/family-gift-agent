"""Verwandtschaft eintragen, abfragen und Wörter wie „Mama“ einer Person zuordnen."""
from dataclasses import dataclass
from itertools import combinations

from ..domain.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from ..domain.kinship import (SYMMETRIC, Fact, FamilyTree, Gender, Kin, KinTerm, name_of, parse_term,
                              require_term)
from ..domain.models import Actor, Person
from ..storage import Database, PersonRepository, RelationRepository

# Diese Beziehungen schließen sich gegenseitig aus (z.B. Elternteil und Geschwister zugleich)
_EXCLUSIVE = frozenset({Kin.PARENT, Kin.CHILD, Kin.SIBLING, Kin.PARTNER, Kin.GRANDPARENT, Kin.GRANDCHILD})
_DOWNWARD = frozenset({Kin.CHILD, Kin.GRANDCHILD, Kin.NIECE_NEPHEW, Kin.CHILD_IN_LAW})
_KIN_ORDER = list(Kin)


@dataclass(frozen=True)
class Relative:
    person: Person
    names: list[str]      # wie diese Person zur betrachteten steht, z.B. ["Mutter"]


@dataclass(frozen=True)
class RelationChange:
    statement: str        # „Ulrike ist Mutter von Timmo“
    known_before: bool
    derived: list[str]    # was sich daraus zusätzlich ergibt


def _names(kins: set[Kin], gender: str | None) -> list[str]:
    return [name_of(k, Gender(gender) if gender else None) for k in sorted(kins, key=_KIN_ORDER.index)]


class PersonResolver:
    """Findet die gemeinte Person: zuerst über den Namen, sonst über ein Verwandtschaftswort aus Sicht
    der fragenden Person („Mama“, „meine Schwester“)."""

    def __init__(self, persons: PersonRepository, relations: RelationRepository):
        self._persons = persons
        self._relations = relations

    def resolve(self, speaker: Person, word: str) -> Person:
        if person := self._persons.by_name(word):
            return person
        if term := parse_term(word):
            return self._by_term(speaker, word, term)
        return self._persons.require(word)

    def candidates(self, speaker: Person, term: KinTerm) -> list[Person]:
        tree = FamilyTree(self._relations.all())
        matching = [self._persons.by_id(pid) for pid, kins in tree.relations(speaker.id).items() if term.kin in kins]
        if term.gender:
            exact = [p for p in matching if p.gender == term.gender]
            return exact or [p for p in matching if p.gender is None]
        return matching

    def _by_term(self, speaker: Person, word: str, term: KinTerm) -> Person:
        found = self.candidates(speaker, term)
        if len(found) == 1:
            return found[0]
        if found:
            names = ", ".join(sorted(p.name for p in found))
            raise ConflictError(f"Mit „{word}“ können mehrere gemeint sein: {names}. Bitte den Namen nennen.")
        raise NotFoundError(f"Ich weiß noch nicht, wer „{word}“ von {speaker.name} ist. Sag es mir z.B. so: "
                            f"„Ulrike ist meine Mutter“.")


class Guardianship:
    """Eltern verwalten die Wunschliste ihrer Kinder, solange diese keinen eigenen Login haben."""

    def __init__(self, persons: PersonRepository, relations: RelationRepository):
        self._persons = persons
        self._relations = relations

    def is_guardian(self, guardian_id: int, person_id: int) -> bool:
        person = self._persons.by_id(person_id)
        if not person or person.is_registered:
            return False
        return Kin.PARENT in FamilyTree(self._relations.all()).kins(guardian_id, person_id)


class RelationService:
    def __init__(self, db: Database, persons: PersonRepository, relations: RelationRepository,
                 resolver: PersonResolver):
        self._db = db
        self._persons = persons
        self._relations = relations
        self._resolver = resolver

    def resolve(self, actor: Actor, word: str) -> Person:
        return self._resolver.resolve(actor.person, word)

    def relatives(self, person: Person) -> list[Relative]:
        """Alle bekannten Verwandten, nächste zuerst."""
        tree = FamilyTree(self._relations.all())
        found = []
        for pid, kins in tree.relations(person.id).items():
            other = self._persons.by_id(pid)
            found.append((min(_KIN_ORDER.index(k) for k in kins), other.name, Relative(other, _names(kins, other.gender))))
        return [r for *_, r in sorted(found, key=lambda t: t[:2])]

    def add(self, actor: Actor, person_word: str, term_word: str, relative_word: str) -> RelationChange:
        """„<person> ist <Begriff> von <relative>“, z.B. Ulrike ist Mutter von Timmo."""
        term = require_term(term_word)
        with self._db.transaction():
            person, relative = self._pair(actor, person_word, relative_word)
            self._check_gender(person, term)
            if term.gender and not person.gender:
                self._persons.set_gender(person.id, term.gender)
            facts = self._relations.all()
            before = FamilyTree(facts)
            existing = before.kins(person.id, relative.id)
            statement = f"{person.name} ist {name_of(term.kin, term.gender)} von {relative.name}"
            if term.kin in existing:
                derived = []
            elif existing:
                raise ConflictError(f"{person.name} ist laut meinen Angaben schon "
                                    f"{' und '.join(_names(existing, person.gender))} von {relative.name}. "
                                    "Falls das nicht stimmt, bitte zuerst diese Angabe entfernen.")
            else:
                fact = Fact(person.id, relative.id, term.kin)
                after = FamilyTree([*facts, fact])
                self._check_consistent(after)
                self._relations.add(fact, created_by=actor.id)
                derived = self._new_relations(before, after, skip=(person.id, relative.id))
        return RelationChange(statement, known_before=term.kin in existing, derived=derived)

    def remove(self, actor: Actor, person_word: str, term_word: str, relative_word: str) -> str:
        term = require_term(term_word)
        with self._db.transaction():
            person, relative = self._pair(actor, person_word, relative_word)
            if not (actor.is_admin or actor.id in (person.id, relative.id)):
                raise PermissionDeniedError("Verwandtschaft entfernen können nur die beiden Beteiligten "
                                            "oder der Admin.")
            statement = f"{person.name} ist {name_of(term.kin, term.gender)} von {relative.name}"
            if self._relations.delete(Fact(person.id, relative.id, term.kin)):
                return statement
            if term.kin in FamilyTree(self._relations.all()).kins(person.id, relative.id):
                raise ConflictError(f"„{statement}“ ergibt sich aus anderen Angaben (z.B. über Geschwister "
                                    "oder Eltern). Bitte die Angabe entfernen, aus der es folgt.")
            raise NotFoundError(f"Dass {statement}, ist nicht gespeichert.")

    def _pair(self, actor: Actor, person_word: str, relative_word: str) -> tuple[Person, Person]:
        person = self._resolver.resolve(actor.person, person_word)
        relative = self._resolver.resolve(actor.person, relative_word)
        if person.id == relative.id:
            raise DomainError("Eine Person kann nicht mit sich selbst verwandt sein.")
        return person, relative

    @staticmethod
    def _check_gender(person: Person, term: KinTerm) -> None:
        if term.gender and person.gender and person.gender != term.gender:
            known = "weiblich" if person.gender == Gender.FEMALE else "männlich"
            raise ConflictError(f"{person.name} ist als {known} eingetragen – passt nicht zu "
                                f"„{name_of(term.kin, term.gender)}“.")

    def _check_consistent(self, tree: FamilyTree) -> None:
        """Lehnt Widersprüche ab, z.B. jemand wäre zugleich Elternteil und Geschwister (oder sein eigener Opa)."""
        ids = [p.id for p in self._persons.all()]
        for a, b in combinations(ids, 2):
            if len(tree.kins(a, b) & _EXCLUSIVE) > 1:
                raise ConflictError(f"Das widerspricht anderen Angaben: {self._persons.by_id(a).name} wäre dann "
                                    f"{' und '.join(_names(tree.kins(a, b), None))} von "
                                    f"{self._persons.by_id(b).name}.")

    def _new_relations(self, before: FamilyTree, after: FamilyTree, skip: tuple[int, int]) -> list[str]:
        """Was durch die neue Angabe zusätzlich folgt – je Paar nur eine Richtung („Mutter“, nicht auch „Tochter“)."""
        derived = []
        for person in self._persons.all():
            for pid, kins in after.relations(person.id).items():          # pid ist <kins> von person
                if {pid, person.id} == set(skip):
                    continue
                new = {k for k in kins - before.kins(pid, person.id)
                       if k not in _DOWNWARD and (k not in SYMMETRIC or pid < person.id)}
                if new:
                    other = self._persons.by_id(pid)
                    derived.append(f"{other.name} ist {' und '.join(_names(new, other.gender))} von {person.name}")
        return derived
