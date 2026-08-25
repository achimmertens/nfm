"""Description filter functions for various news sources."""

import re

CLEANR = re.compile('<.*?>')  # regex to remove HTML tags


def _remove_html_tags(raw_html):
    """Remove HTML tags from raw HTML string."""
    cleantext = re.sub(CLEANR, '', raw_html)
    return cleantext


def desc_filter_golem(desc: str) -> str:
    """Filter description for Golem feeds."""
    # return everything from up to '(<a href'
    if '(<a href' in desc:
        return desc.split('(<a href')[0]
    else:
        return desc


def desc_filter_tarnkappe(desc: str) -> str:
    """Filter description for Tarnkappe feeds."""
    # return everything between '<p>' and '</p>
    if '</p>' in desc:
        return desc.split('</p>')[0][3:]
    else:
        return desc


def desc_filter_postillion(desc: str) -> str:
    """Filter description for Postillion feeds."""
    return ""


def desc_filter_youtube(desc: str) -> str:
    """Filter description for YouTube feeds."""
    return ""


def desc_filter_derstandard(desc: str) -> str:
    """Filter description for Der Standard feeds."""
    x = _remove_html_tags(desc).strip()
    if x[-1] == ".":
        return x
    else:
        return x + "."


def desc_filter_decoder(desc: str) -> str:
    """Filter description for Decoder feeds."""
    x = desc.split("<p>")
    if len(x) > 1:
        return _remove_html_tags(x[2]).strip()
    return ""


def desc_filter_winfuture(desc: str) -> str:
    """Filter description for WinFuture feeds."""
    x = _remove_html_tags(desc).strip()
    x = x.split(" (Weiter lesen)")
    return x[0]


def desc_filter_smartdroid(desc: str) -> str:
    """Filter description for SmartDroid feeds."""
    x = _remove_html_tags(desc).strip()
    x = x.split("&#8230;")
    return x[0] + " ..."


def desc_filter_gs(desc: str) -> str:
    """Filter description for Google News feeds."""
    return _remove_html_tags(desc).split("&nbsp;")[0] + "."


def desc_filter_fr(desc: str) -> str:
    """Filter description for FR feeds."""
    return _remove_html_tags(desc)


def desc_filter_heise(desc: str) -> str:
    """Filter description for Heise feeds (strip HTML + trailing link boilerplate)."""
    x = _remove_html_tags(desc).strip()
    # Heise descriptions often end with a ' (Weiterlesen…)' / link suffix.
    for sep in (" (Weiterlesen", " (weiterlesen", " Weiterlesen", " …"):
        if sep in x:
            x = x.split(sep)[0]
            break
    return x.strip()


def desc_filter_netzpolitik(desc: str) -> str:
    """Filter description for Netzpolitik feeds (strip HTML)."""
    return _remove_html_tags(desc).strip()


def desc_filter_t3n(desc: str) -> str:
    """Filter description for t3n feeds (strip HTML + trailing boilerplate)."""
    x = _remove_html_tags(desc).strip()
    for sep in (" (Weiterlesen", " (weiterlesen", " Weiterlesen", " …"):
        if sep in x:
            x = x.split(sep)[0]
            break
    return x.strip()
