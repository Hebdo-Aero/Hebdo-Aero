"""Lecture des flux RSS / Atom de la semaine (bibliothèque standard uniquement)."""
from __future__ import annotations

import html
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .http import ErreurHTTP, requete

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class Article:
    source: str
    titre: str
    url: str
    publie: datetime
    extrait: str


class _Texte(HTMLParser):
    def __init__(self):
        super().__init__()
        self.morceaux: list[str] = []

    def handle_data(self, data):
        self.morceaux.append(data)


def texte_brut(fragment: str) -> str:
    if not fragment:
        return ""
    p = _Texte()
    p.feed(fragment)
    texte = html.unescape(" ".join(p.morceaux))
    texte = re.sub(r"(The post|L[’']article) .{0,200}?(appeared first on|est apparu en premier sur|a été publié sur).*$",
                   "", texte, flags=re.S)
    return re.sub(r"\s+", " ", texte).strip()


def normaliser_url(url: str) -> str:
    """Forme canonique pour comparer deux liens (sans traqueurs ni barre finale)."""
    url = (url or "").strip()
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    hote = p.netloc.lower().removeprefix("www.")
    requete_ = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                if not k.lower().startswith(("utm_", "fbclid", "gclid", "mc_"))]
    chemin = p.path.rstrip("/") or "/"
    return urlunsplit(("https", hote, chemin, urlencode(requete_), ""))


def _date(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    valeur = valeur.strip()
    try:
        d = parsedate_to_datetime(valeur)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _txt(el, chemin: str) -> str:
    trouve = el.find(chemin, NS)
    return (trouve.text or "").strip() if trouve is not None and trouve.text else ""


def analyser(xml: bytes, source: str) -> list[Article]:
    racine = ET.fromstring(xml)
    articles: list[Article] = []
    items = racine.findall("./channel/item") or racine.findall(".//item")
    for it in items:
        resume = texte_brut(_txt(it, "description"))
        contenu = texte_brut(_txt(it, "content:encoded"))
        articles.append(Article(
            source=source,
            titre=texte_brut(_txt(it, "title")),
            url=_txt(it, "link"),
            publie=_date(_txt(it, "pubDate") or _txt(it, "dc:date")),
            extrait=contenu if len(resume) < 200 and contenu else resume,
        ))
    for e in racine.findall("atom:entry", NS):
        lien = ""
        for l in e.findall("atom:link", NS):
            if l.get("rel", "alternate") == "alternate":
                lien = l.get("href", "")
                break
        resume = texte_brut(_txt(e, "atom:summary"))
        contenu = texte_brut(_txt(e, "atom:content"))
        articles.append(Article(
            source=source,
            titre=texte_brut(_txt(e, "atom:title")),
            url=lien,
            publie=_date(_txt(e, "atom:published") or _txt(e, "atom:updated")),
            extrait=contenu if len(resume) < 200 and contenu else resume,
        ))
    return [a for a in articles if a.titre and a.url and a.publie]


def collecter(flux: list[dict], debut: date, fin: date, fuseau: str = "Europe/Paris",
              max_par_flux: int = 60) -> list[Article]:
    """Articles publiés entre `debut` et `fin` inclus (jours comptés à l'heure de `fuseau`)."""
    tz = ZoneInfo(fuseau)
    retenus: dict[str, Article] = {}
    for f in flux:
        try:
            _, _, xml = requete(f["url"], delai=30, essais=2,
                                entetes={"Accept": "application/rss+xml, application/atom+xml, */*"})
            articles = analyser(xml, f["nom"])
        except (ErreurHTTP, ET.ParseError) as e:
            print(f"  ! flux ignoré ({f['nom']}) : {e}", file=sys.stderr)
            continue
        gardes = 0
        for a in sorted(articles, key=lambda a: a.publie, reverse=True):
            if debut <= a.publie.astimezone(tz).date() <= fin and gardes < max_par_flux:
                retenus.setdefault(normaliser_url(a.url), a)
                gardes += 1
        print(f"  {f['nom']} : {gardes} article(s) de la semaine")
    return sorted(retenus.values(), key=lambda a: a.publie)
